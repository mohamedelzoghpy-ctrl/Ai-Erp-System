"""تكامل منظومة الفاتورة الإلكترونية المصرية (ETA).

جاهز حتى لحظة تسجيل الشركة: بمجرد استلام client_id/client_secret من بوابة
المنظومة تُضبط من صفحة الإعداد ويشتغل الإرسال الحقيقي. قبل ذلك تعمل بيئة
«mock» محليًا (توافق كامل للسير والاختبار بلا شبكة).

المكونات:
- canonicalize(): التسلسل الكانوني (مفاتيح مرتبة أبجديًا بشكل عميق، بلا فواصل) — أساس الهاش والتوقيع.
- build_invoice_document(): بناء مستند الفاتورة I / الإشعار الدائن C حسب مواصفات ETA v1.0.
- sign_document(): توقيع C14B = RSA-SHA256(PKCS1v15) على هاش SHA256 للكانونيكال (Base64).
- generate_keypair_and_csr(): توليد زوج مفاتيح + CSR (CN=TIN) لرفعه في بوابة التسجيل.
- EtaClient: توكن (client_credentials مع تخزين مؤقت) · إرسال دفعة · متابعة حالة مستند.
  بيئة mock: قبول فوري بـ submissionUUID وحالة valid — بلا طلبات خارجية.

المرجع: مواصفات JSON للفاتورة الإلكترونية (eInvoice JSON, documentTypeVersion 1.0)
— حقول أساسية فقط الآن: issuer/receiver/invoiceLines/taxTotals + التوقيع.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid as _uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

# بيئات ETA الرسمية (تُضبط لاحقًا من الإعداد إن تغيّرت)
ETA_URLS = {
    "sandbox": {
        "id": "https://id.preprod.eta.gov.eg/connect/token",
        "api": "https://api.preprod.eta.gov.eg/api/v1",
    },
    "prod": {
        "id": "https://id.eta.gov.eg/connect/token",
        "api": "https://api.invoicing.eta.gov.eg/api/v1",
    },
}


class EtaNotConfigured(Exception):
    """البيئة غير مضبوطة (بيانات الدخول ناقصة) — برسالة عربية واضحة."""


# ---------------------------------------------------------------- canonical + signing
def canonicalize(document: Dict[str, Any]) -> bytes:
    """الكانونيكال الرسمي: مفاتيح مرتبة أبجديًا بشكل عميق، فواصل بلا مسافات."""
    return json.dumps(document, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def document_hash(document: Dict[str, Any]) -> str:
    return base64.b64encode(hashlib.sha256(canonicalize(document)).digest()).decode()


def sign_document(document: Dict[str, Any], private_key_pem: bytes) -> str:
    """توقيع C14B: RSA-SHA256 (PKCS1v15) على هاش الكانونيكال — Base64."""
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    digest = hashlib.sha256(canonicalize(document)).digest()
    sig = key.sign(digest, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def verify_signature(document: Dict[str, Any], signature_b64: str, public_key_pem: bytes) -> bool:
    key = serialization.load_pem_public_key(public_key_pem)
    digest = hashlib.sha256(canonicalize(document)).digest()
    try:
        key.verify(base64.b64decode(signature_b64), digest, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


def generate_keypair_and_csr(tin: str, organization: str = "") -> Dict[str, str]:
    """توليد زوج RSA-2048 + CSR (CN=TIN) — الـ CSR يُرفع في بوابة المنظومة أثناء التسجيل،
    والخاص يُخزن مشفرًا لدى الشركة للتوقيع. لا يُشترط إنترنت."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, tin),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization or tin),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "EG"),
        ]))
        .sign(key, hashes.SHA256())
    )
    return {
        "private_key": key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
        ).decode(),
        "csr": csr.public_bytes(serialization.Encoding.PEM).decode(),
        "public_key": key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode(),
    }


# ---------------------------------------------------------------- بناء المستند
DEFAULT_ADDR = {"country": "EG", "governate": "", "regionCity": "", "street": "", "buildingNumber": "0"}


def _money(v) -> float:
    return float(Decimal(str(v or 0)).quantize(Decimal("0.01")))


def build_document(
    *,
    document_type: str,  # "I" فاتورة / "C" إشعار دائن (مرتجع)
    internal_id: str,
    issuer_tin: str,
    issuer_name: str,
    receiver_name: str,
    receiver_type: str = "P",  # B شركة مسجلة / P شخص
    receiver_id: str = "",
    lines: List[Dict[str, Any]],
    vat_rate: float = 0.0,
    issued_at: Optional[datetime] = None,
    reference: Optional[Dict[str, str]] = None,  # للإشعار الدائن: {uuid/longId/internalId} الأصل
    document_type_version: str = "1.0",
    issuer_address: Optional[Dict[str, str]] = None,
    receiver_address: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    issued = issued_at or datetime.now(timezone.utc)
    doc: Dict[str, Any] = {
        "documentType": document_type,
        "documentTypeVersion": document_type_version,
        "dateTimeIssued": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "taxpayerActivityCode": "4690",
        "internalID": internal_id,
        "issuer": {
            "type": "B", "id": issuer_tin, "name": issuer_name,
            "address": {**DEFAULT_ADDR, **(issuer_address or {})},
        },
        "receiver": {
            "type": receiver_type, "id": receiver_id or "", "name": receiver_name,
            "address": {**DEFAULT_ADDR, **(receiver_address or {})},
        },
        "invoiceLines": [],
    }
    total_sales = Decimal("0")
    for ln in lines:
        unit_price = Decimal(str(ln.get("unit_price") or 0))
        qty = Decimal(str(ln.get("quantity") or 0))
        line_total = (unit_price * qty).quantize(Decimal("0.01"))
        total_sales += line_total
        doc["invoiceLines"].append({
            "description": ln.get("description") or f"صنف #{ln.get('product_id', '')}",
            "itemType": "GS1",
            "unitType": "EA",
            "quantity": float(qty),
            "internalCode": ln.get("internal_code") or str(ln.get("product_id", "")),
            "salesTotal": _money(line_total),
            "total": _money(line_total),
            "valueDifference": 0,
            "unitValue": {"currencySold": "EGP", "amountEGP": _money(unit_price)},
        })
    doc["totalSalesAmount"] = _money(total_sales)
    doc["netAmount"] = _money(total_sales)
    vat = (total_sales * Decimal(str(vat_rate)) / Decimal("100")).quantize(Decimal("0.01"))
    doc["taxTotals"] = [{"taxType": "T1", "amount": _money(vat)}]
    doc["totalAmount"] = _money(total_sales + vat)
    doc["totalDiscountAmount"] = 0
    doc["extraDiscountAmount"] = 0
    doc["totalItemsDiscountAmount"] = 0
    if document_type == "C":
        doc["references"] = [reference or {}]
    return doc


# ---------------------------------------------------------------- العميل
class EtaClient:
    """عميل المنظومة: mock (بلا شبكة) / sandbox / prod بالتوكن المخزن مؤقتًا."""

    def __init__(self, env: str, client_id: str = "", client_secret: str = "",
                 base_url: Optional[str] = None, id_url: Optional[str] = None):
        self.env = env
        self.client_id = client_id
        self.client_secret = client_secret
        self._id_url = id_url
        self._api_url = base_url
        self._token: Optional[str] = None
        self._token_exp: float = 0

    # -- التوكين
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if self.env == "mock":
            self._token = f"mock-token-{_uuid.uuid4().hex[:12]}"
            self._token_exp = time.time() + 3600
            return self._token
        if not self.client_id or not self.client_secret:
            raise EtaNotConfigured("بيانات الدخول للمنظومة (client_id/secret) غير مضبوطة — أدخلها من صفحة الفاتورة الإلكترونية")
        import urllib.parse
        import urllib.request
        urls = ETA_URLS.get(self.env, ETA_URLS["sandbox"])
        id_url = self._id_url or urls["id"]
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "InvoicingAPI",
        }).encode()
        req = urllib.request.Request(id_url, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode())
        except Exception as exc:
            raise EtaNotConfigured(f"فشل الحصول على التوكن من المنظومة: {exc}") from exc
        self._token = body.get("access_token")
        self._token_exp = time.time() + int(body.get("expires_in", 3600))
        if not self._token:
            raise EtaNotConfigured("استجابة توكن غير سليمة من المنظومة")
        return self._token

    def _api_base(self) -> str:
        if self._api_url:
            return self._api_url.rstrip("/")
        return ETA_URLS.get(self.env, ETA_URLS["sandbox"])["api"]

    # -- العمليات
    def submit_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """إرسال دفعة (حتى 100 مستند) — يرجع submissionUUID وحالة كل مستند."""
        if self.env == "mock":
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return {
                "submissionUUID": str(_uuid.uuid4()),
                "acceptedDocuments": [
                    {"uuid": str(_uuid.uuid4()), "longId": f"MOCK-{i:06d}", "internalId": d.get("internalID", ""), "status": "Valid"}
                    for i, d in enumerate(documents, 1)
                ],
                "rejectedDocuments": [],
                "dateTimeReceived": now,
                "documentSummary": [],
            }
        import urllib.request
        token = self._get_token()
        req = urllib.request.Request(
            f"{self._api_base()}/documentsubmissions",
            data=json.dumps({"documents": documents}, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def get_document(self, eta_uuid: str) -> Optional[Dict[str, Any]]:
        """متابعة حالة مستند (Valid/Invalid/Submitted/Cancelled)."""
        if self.env == "mock":
            return {"uuid": eta_uuid, "status": "Valid", "longId": f"MOCK-{eta_uuid[:6]}"}
        import urllib.request
        token = self._get_token()
        req = urllib.request.Request(
            f"{self._api_base()}/documents/{eta_uuid}/raw",
            method="GET",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return None


# ---------------------------------------------------------------- إيصال البيع (R)
def build_receipt_document(
    *,
    internal_id: str,
    issuer_tin: str,
    issuer_name: str,
    receiver_name: str,
    lines: List[Dict[str, Any]],
    vat_rate: float = 0.0,
    issued_at: Optional[datetime] = None,
    issuer_address: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """إيصال بيع (documentType R) — لمبيعات نقاط البيع B2C.

    مع نسبة VAT: كل سطر يحمل taxTotals (T1) وإجمالي السطر شامل الضريبة،
    والمستند يحمل taxTotals مجمّعة — حسب إصدار 1.0 من إيصالات المنظومة.

    ملاحظة تشغيلية: في الإنتاج تتطلب الإيصالات توقيع SDK الجهاز المسجل —
    في mock تعمل كاملة الآن، وعند التفعيل يُستكمل توقيع الجهاز."""
    issued = issued_at or datetime.now(timezone.utc)
    rate = Decimal(str(vat_rate or 0))
    total_sales = Decimal("0")
    total_vat = Decimal("0")
    lines_out = []
    for ln in lines:
        unit_price = Decimal(str(ln.get("unit_price") or 0))
        qty = Decimal(str(ln.get("quantity") or 0))
        line_sales = (unit_price * qty).quantize(Decimal("0.01"))
        line_vat = (line_sales * rate / Decimal("100")).quantize(Decimal("0.01")) if rate > 0 else Decimal("0")
        total_sales += line_sales
        total_vat += line_vat
        row = {
            "internalCode": ln.get("internal_code") or str(ln.get("product_id", "")),
            "description": ln.get("description") or f"صنف #{ln.get('product_id', '')}",
            "itemType": "GS1",
            "unitType": "EA",
            "quantity": float(qty),
            "unitValue": {"currencySold": "EGP", "amountEGP": _money(unit_price)},
            "salesTotal": _money(line_sales),
            "total": _money(line_sales + line_vat),
        }
        if line_vat > 0:
            row["taxTotals"] = [{"taxType": "T1", "amount": _money(line_vat), "rate": float(rate)}]
        lines_out.append(row)
    document = {
        "documentType": "R",
        "documentTypeVersion": "1.0",
        "dateTimeIssued": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "taxpayerActivityCode": "4690",
        "internalID": internal_id,
        "issuer": {
            "type": "B", "id": issuer_tin, "name": issuer_name,
            "address": {**DEFAULT_ADDR, **(issuer_address or {})},
        },
        "receiver": {
            "type": "P", "id": "", "name": receiver_name,
            "address": {**DEFAULT_ADDR},
        },
        "receiptLines": lines_out,
        "totalSalesAmount": _money(total_sales),
        "extraReceiptsAmount": _money(Decimal("0")),
        "netAmount": _money(total_sales),
        "totalAmount": _money(total_sales + total_vat),
    }
    if total_vat > 0:
        document["taxTotals"] = [{"taxType": "T1", "amount": _money(total_vat), "rate": float(rate)}]
    return document


# ---------------------------------------------------------------- المستندات الواردة (مشتريات)
def fetch_new_purchase_documents(env: str, client_id: str = "", client_secret: str = "") -> List[Dict[str, Any]]:
    """جلب فواتير المشتريات الواردة من المنظومة (موردين أرسلوا إلكترونيًا).

    mock: عينتان واقعيتا الشكل · sandbox/prod: GET /documents/new ثم /documents/{uuid}/raw."""
    if env == "mock":
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return [
            {
                "uuid": str(_uuid.uuid4()),
                "issuer": {"id": "300012345600003", "name": "شركة التوريدات المصرية"},
                "internalID": "SUP-INV-2041",
                "dateTimeIssued": now,
                "totalAmount": 5700.0,
                "buyerTin": None,
                "documentType": "I",
                "invoiceLines": [
                    {"description": "زيت محركات 5 لتر", "internalCode": "OIL-5L", "quantity": 20, "unitPrice": 250.0, "salesTotal": 5000.0},
                    {"description": "فلاتر زيت", "internalCode": "FLT-Z", "quantity": 10, "unitPrice": 70.0, "salesTotal": 700.0},
                ],
            },
            {
                "uuid": str(_uuid.uuid4()),
                "issuer": {"id": "300098765400003", "name": "مؤسسة الورق الحديثة"},
                "internalID": "WRQ-8890",
                "dateTimeIssued": now,
                "totalAmount": 1180.0,
                "buyerTin": None,
                "documentType": "I",
                "invoiceLines": [
                    {"description": "أوراق طباعة A4", "internalCode": "PAP-A4", "quantity": 20, "unitPrice": 50.0, "salesTotal": 1000.0},
                ],
            },
        ]
    import urllib.request
    # prod flow: يحتاج توكن — يُستكمل عند التسجيل (يستدعي get_token عبر المُنشئ الكامل)
    token = None
    if client_id and client_secret:
        tmp = EtaClient(env=env, client_id=client_id, client_secret=client_secret)
        token = tmp._get_token()
    if token is None:
        raise EtaNotConfigured("بيانات الدخول مطلوبة لجلب المستندات الواردة")
    base = ETA_URLS.get(env, ETA_URLS["sandbox"])["api"]
    req = urllib.request.Request(f"{base}/documents/new", method="GET",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    out = []
    for d in payload.get("documents", []):
        try:
            req2 = urllib.request.Request(f"{base}/documents/{d['uuid']}/raw", method="GET",
                                          headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req2, timeout=30) as resp2:
                out.append(json.loads(resp2.read().decode()))
        except Exception:
            continue
    return out
