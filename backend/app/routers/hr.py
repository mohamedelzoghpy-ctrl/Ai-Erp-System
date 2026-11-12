"""الموارد البشرية (HR): المسميات الوظيفية والدرجات وملفات الموظفين والعقود
والمستندات والسجل الوظيفي.

كل البيانات محكومة بالشركة (tenant) مثل بقية الوحدات، وكل عملية كتابة تُسجَّل
في سجل التدقيق (audit) قبل الالتزام. قراءة الرواتب والحسابات البنكية للموظف
متاحة لبقية المستخدمين إلا أن تعديلها للمدراء وفوقهم فقط (require_manager).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..audit import audit
from ..codegen import unique_code
from ..database import get_db
from ..deps import get_current_user, require_manager, require_permission_or_role, user_role
from ..pagination import paginate
from ..permissions import apply_field_masks

router = APIRouter(prefix="/hr", tags=["hr"])

_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 ميجابايت
_ALLOWED_DOC_MIMES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
}


# ------------------------------------------------------------------ helpers

def _role(user: models.User) -> str:
    return user_role(user)


def _is_manager(user: models.User) -> bool:
    return _role(user) in ("admin", "manager")


def _employee_out(db: Session, emp: models.HrEmployee) -> schemas.HrEmployeeOut:
    out = schemas.HrEmployeeOut.model_validate(emp)
    out.contracts_count = db.query(models.HrContract).filter(models.HrContract.employee_id == emp.id).count()
    apply_field_masks("HrEmployee", out)
    return out


def _detail_out(emp: models.HrEmployee) -> schemas.HrEmployeeDetailOut:
    out = schemas.HrEmployeeDetailOut.model_validate(emp)
    apply_field_masks("HrEmployee", out)
    return out


def _document_out(doc: models.HrDocument) -> schemas.HrDocumentOut:
    out = schemas.HrDocumentOut.model_validate(doc)
    out.has_file = doc.file_blob is not None
    return out


def _validate_fk(db: Session, company_id: int, payload_field: Optional[int], model, label: str) -> Optional[int]:
    """يتحقق أن الكيان المُشار إليه تابع لنفس الشركة (أو является None)."""
    if payload_field is None:
        return None
    row = db.get(model, payload_field)
    if row is None or getattr(row, "company_id", None) != company_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{label} غير موجود في هذه الشركة")
    return payload_field


def _employee_or_404(db: Session, employee_id: int) -> models.HrEmployee:
    emp = (
        db.query(models.HrEmployee)
        .filter(models.HrEmployee.company_id == db.info["company_id"], models.HrEmployee.id == employee_id)
        .one_or_none()
    )
    if emp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الموظف غير موجود")
    return emp


def _validate_user_link(db: Session, company_id: int, user_id: Optional[int], exclude_id: Optional[int] = None) -> None:
    """ربط حساب دخول بملف موظف: الحساب موجود في نفس الشركة وغير مرتبط بموظف آخر."""
    if user_id is None:
        return
    link_user = db.get(models.User, user_id)
    if link_user is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "حساب الدخول غير موجود")
    member = (
        db.query(models.UserCompanyMembership)
        .filter(models.UserCompanyMembership.user_id == user_id, models.UserCompanyMembership.company_id == company_id)
        .first()
    )
    if member is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "حساب الدخول لا ينتمي إلى هذه الشركة")
    taken = (
        db.query(models.HrEmployee)
        .filter(
            models.HrEmployee.company_id == company_id,
            models.HrEmployee.user_id == user_id,
            models.HrEmployee.id != (exclude_id or -1),
        )
        .first()
    )
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "حساب الدخول مرتبط بموظف آخر في هذه الشركة")


def _employee_for_user(db: Session, user: models.User) -> models.HrEmployee:
    """ملف الموظف المرتبط بحساب الدخول (ESS) — 404 إن لم يكن مرتبطاً."""
    emp = (
        db.query(models.HrEmployee)
        .filter(models.HrEmployee.company_id == db.info["company_id"], models.HrEmployee.user_id == user.id)
        .one_or_none()
    )
    if emp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "حسابك غير مرتبط بملف موظف — راجع إدارة الموارد البشرية")
    return emp


def _company_lookup(db: Session, company_id: int, model, name: str):
    return db.query(model).filter(model.company_id == company_id).order_by(model.name, model.id).all()


def _national_id_taken(db: Session, company_id: int, national_id: Optional[str], exclude_id: Optional[int] = None) -> bool:
    if not national_id:
        return False
    q = db.query(models.HrEmployee).filter(
        models.HrEmployee.company_id == company_id,
        models.HrEmployee.national_id == national_id,
    )
    if exclude_id:
        q = q.filter(models.HrEmployee.id != exclude_id)
    return q.first() is not None


def _snapshot_move(
    db: Session,
    emp: models.HrEmployee,
    payload: schemas.HrEmployeeMoveCreate,
    user: models.User,
    from_snapshot: Optional[dict] = None,
) -> models.HrEmployeeMove:
    """تسجيل تحرك وظيفي وتطبيق أثره على ملف الموظف في نفس العملية.

    `from_snapshot` اختياري: قيم الحالة «قبل التعديل» للحقول (department_id،
    job_title_id، basic_salary) — يُستخدم في التعديل المباشر حيث تغيّرت القيم على
    الكائن مسبقًا في هذه الجلسة.
    """
    company_id = db.info["company_id"]
    effective = payload.effective_date or date.today()
    to_department_id = _validate_fk(db, company_id, payload.to_department_id, models.Department, "الإدارة")
    to_job_title_id = _validate_fk(db, company_id, payload.to_job_title_id, models.HrJobTitle, "المسمى الوظيفي")
    move = models.HrEmployeeMove(
        company_id=company_id,
        employee_id=emp.id,
        move_type=payload.move_type,
        effective_date=effective,
        from_department_id=(from_snapshot or {}).get("department_id", emp.department_id),
        to_department_id=to_department_id,
        from_job_title_id=(from_snapshot or {}).get("job_title_id", emp.job_title_id),
        to_job_title_id=to_job_title_id,
        from_salary=(from_snapshot or {}).get("basic_salary", emp.basic_salary),
        to_salary=payload.to_salary,
        reason=payload.reason,
        created_by=user.id,
    )
    applied: List[str] = []
    if payload.move_type == "termination":
        emp.status = "terminated"  # type: ignore[assignment]
        emp.terminated_at = effective  # type: ignore[assignment]
        emp.is_active = False  # type: ignore[assignment]
        applied.append("الحالة: منتهي الخدمة")
    elif payload.new_status:
        emp.status = payload.new_status  # type: ignore[assignment]
        applied.append(f"الحالة: {payload.new_status}")
    if to_department_id is not None:
        emp.department_id = to_department_id  # type: ignore[assignment]
        applied.append("الإدارة")
    if to_job_title_id is not None:
        emp.job_title_id = to_job_title_id  # type: ignore[assignment]
        applied.append("المسمى الوظيفي")
    if payload.to_salary is not None:
        emp.basic_salary = payload.to_salary  # type: ignore[assignment]
        applied.append("الراتب")
    db.add(move)
    db.flush()
    audit(db, user, "create", "hr_move", move, f"{emp.code} · {payload.move_type} · " + ("، ".join(applied) or payload.reason or ""))
    return move


def _auto_move(db: Session, emp: models.HrEmployee, before: dict, user: models.User) -> None:
    """سجل تلقائي للتحركات عند تعديل ملف الموظف مباشرة (يحفظ التاريخية كاملة)."""
    changed = any(
        before.get(f) != getattr(emp, f)
        for f in ("department_id", "job_title_id", "basic_salary", "status")
    )
    if not changed:
        return
    if before["status"] != "terminated" and emp.status == "terminated":  # type: ignore[union-attr]
        move_type = "termination"
    elif before["status"] != emp.status:  # type: ignore[union-attr]
        move_type = "status_change"
    elif before["department_id"] != emp.department_id or before["job_title_id"] != emp.job_title_id:  # type: ignore[union-attr]
        move_type = "transfer"
    else:
        move_type = "salary_change"
    move = schemas.HrEmployeeMoveCreate(
        move_type=move_type,  # type: ignore[arg-type]
        to_department_id=emp.department_id,
        to_job_title_id=emp.job_title_id,
        to_salary=emp.basic_salary,
        new_status=emp.status,  # type: ignore[arg-type]
        reason="تعديل مباشر لملف الموظف",
    )
    move.effective_date = date.today()
    _snapshot_move(db, emp, move, user, from_snapshot=before)


# ------------------------------------------------------------------ job titles

@router.get("/job-titles", response_model=List[schemas.HrJobTitleOut])
def list_job_titles(
    active_only: bool = False,
    search: Optional[str] = None,
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrJobTitle).filter(models.HrJobTitle.company_id == db.info["company_id"])
    if active_only:
        q = q.filter(models.HrJobTitle.is_active.is_(True))
    if search:
        s = f"%{search.strip()}%"
        q = q.filter(models.HrJobTitle.name.ilike(s))
    rows = q.order_by(models.HrJobTitle.name, models.HrJobTitle.id).all()
    response.headers["X-Total-Count"] = str(len(rows))
    return rows


@router.post("/job-titles", response_model=schemas.HrJobTitleOut, status_code=status.HTTP_201_CREATED)
def create_job_title(payload: schemas.HrJobTitleCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    name = payload.name.strip()
    if db.query(models.HrJobTitle).filter(models.HrJobTitle.company_id == company_id, models.HrJobTitle.name == name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "المسمى الوظيفي مستخدم بالفعل")
    if payload.min_salary is not None and payload.max_salary is not None and payload.max_salary < payload.min_salary:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "أقصى راتب يجب أن يكون أكبر من الحد الأدنى")
    row = models.HrJobTitle(
        company_id=company_id,
        name=name,
        description=payload.description,
        min_salary=payload.min_salary,
        max_salary=payload.max_salary,
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "hr_job_title", row, row.name)
    return row


@router.patch("/job-titles/{job_title_id}", response_model=schemas.HrJobTitleOut)
def update_job_title(job_title_id: int, payload: schemas.HrJobTitleCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = (
        db.query(models.HrJobTitle)
        .filter(models.HrJobTitle.company_id == db.info["company_id"], models.HrJobTitle.id == job_title_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسمى الوظيفي غير موجود")
    data = payload.model_dump(exclude_unset=True)
    name = (data.get("name") or row.name).strip()
    dup = (
        db.query(models.HrJobTitle)
        .filter(models.HrJobTitle.company_id == db.info["company_id"], models.HrJobTitle.id != job_title_id, models.HrJobTitle.name == name)
        .first()
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "المسمى الوظيفي مستخدم بالفعل")
    row.name = name
    row.description = data.get("description")
    row.min_salary = data.get("min_salary")
    row.max_salary = data.get("max_salary")
    row.is_active = data.get("is_active", row.is_active)
    audit(db, user, "update", "hr_job_title", row, row.name)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/job-titles/{job_title_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job_title(job_title_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = (
        db.query(models.HrJobTitle)
        .filter(models.HrJobTitle.company_id == db.info["company_id"], models.HrJobTitle.id == job_title_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسمى الوظيفي غير موجود")
    used = (db.query(models.HrEmployee).filter(models.HrEmployee.job_title_id == row.id).count()) + (
        db.query(models.HrEmployeeMove).filter(models.HrEmployeeMove.to_job_title_id == row.id).count()
    )
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن الحذف: المسمى مرتبط بموظفين — أوقف تفعيله بدلًا من ذلك")
    audit(db, user, "delete", "hr_job_title", row.id, row.name)
    db.delete(row)
    db.commit()


# ------------------------------------------------------------------ grades

@router.get("/grades", response_model=List[schemas.HrGradeOut])
def list_grades(
    active_only: bool = False,
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrGrade).filter(models.HrGrade.company_id == db.info["company_id"])
    if active_only:
        q = q.filter(models.HrGrade.is_active.is_(True))
    rows = q.order_by(models.HrGrade.name, models.HrGrade.id).all()
    response.headers["X-Total-Count"] = str(len(rows))
    return rows


@router.post("/grades", response_model=schemas.HrGradeOut, status_code=status.HTTP_201_CREATED)
def create_grade(payload: schemas.HrGradeCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    name = payload.name.strip()
    if db.query(models.HrGrade).filter(models.HrGrade.company_id == company_id, models.HrGrade.name == name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "الدرجة مستخدمة بالفعل")
    if payload.min_salary is not None and payload.max_salary is not None and payload.max_salary < payload.min_salary:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "أقصى راتب يجب أن يكون أكبر من الحد الأدنى")
    row = models.HrGrade(company_id=company_id, name=name, min_salary=payload.min_salary, max_salary=payload.max_salary, is_active=payload.is_active)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "hr_grade", row, row.name)
    return row


@router.patch("/grades/{grade_id}", response_model=schemas.HrGradeOut)
def update_grade(grade_id: int, payload: schemas.HrGradeCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrGrade).filter(models.HrGrade.company_id == db.info["company_id"], models.HrGrade.id == grade_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الدرجة غير موجودة")
    data = payload.model_dump(exclude_unset=True)
    name = (data.get("name") or row.name).strip()
    dup = (
        db.query(models.HrGrade)
        .filter(models.HrGrade.company_id == db.info["company_id"], models.HrGrade.id != grade_id, models.HrGrade.name == name)
        .first()
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "الدرجة مستخدمة بالفعل")
    row.name = name
    row.min_salary = data.get("min_salary")
    row.max_salary = data.get("max_salary")
    row.is_active = data.get("is_active", row.is_active)
    audit(db, user, "update", "hr_grade", row, row.name)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/grades/{grade_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_grade(grade_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrGrade).filter(models.HrGrade.company_id == db.info["company_id"], models.HrGrade.id == grade_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الدرجة غير موجودة")
    if db.query(models.HrEmployee).filter(models.HrEmployee.grade_id == row.id).count():
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن الحذف: الدرجة مرتبطة بموظفين — أوقف تفعيلها بدلًا من ذلك")
    audit(db, user, "delete", "hr_grade", row.id, row.name)
    db.delete(row)
    db.commit()


# ------------------------------------------------------------------ employees

@router.get("/employees", response_model=List[schemas.HrEmployeeOut])
def list_employees(
    response: Response,
    search: Optional[str] = None,
    employee_status: Optional[str] = None,
    department_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrEmployee).filter(models.HrEmployee.company_id == db.info["company_id"])
    if employee_status:
        q = q.filter(models.HrEmployee.status == employee_status)
    if department_id:
        q = q.filter(models.HrEmployee.department_id == department_id)
    if branch_id:
        q = q.filter(models.HrEmployee.branch_id == branch_id)
    if search:
        s = f"%{search.strip()}%"
        q = q.filter(
            (models.HrEmployee.full_name.ilike(s))
            | (models.HrEmployee.code.ilike(s))
            | (models.HrEmployee.phone.ilike(s))
            | (models.HrEmployee.email.ilike(s))
            | (models.HrEmployee.national_id.ilike(s))
        )
    rows = paginate(q, response, skip, limit, models.HrEmployee.status, models.HrEmployee.full_name)
    return [_employee_out(db, e) for e in rows]


@router.get("/summary")
def hr_summary(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    company_id = db.info["company_id"]
    rows = db.query(models.HrEmployee.status, models.HrEmployee.id).filter(models.HrEmployee.company_id == company_id).all()
    counts = {"active": 0, "probation": 0, "suspended": 0, "terminated": 0}
    for st, _ in rows:
        if st in counts:
            counts[st] += 1
    expiring = (
        db.query(models.HrDocument)
        .filter(
            models.HrDocument.company_id == company_id,
            models.HrDocument.expiry_date.isnot(None),
            models.HrDocument.expiry_date <= date.today(),
        )
        .count()
    )
    return {"total": len(rows), **counts, "expiring_documents": expiring}


@router.get("/employees/{employee_id}", response_model=schemas.HrEmployeeDetailOut)
def get_employee(employee_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    emp = _employee_or_404(db, employee_id)
    return _detail_out(emp)


@router.post("/employees", response_model=schemas.HrEmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(payload: schemas.HrEmployeeCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    full_name = payload.full_name.strip()
    code = (payload.code or "").strip() or unique_code(db, models.HrEmployee, company_id, full_name, "EMP")
    existing = (
        db.query(models.HrEmployee)
        .filter(models.HrEmployee.company_id == company_id, (models.HrEmployee.code == code) | (models.HrEmployee.full_name == full_name))
        .first()
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "اسم الموظف أو الكود مستخدم بالفعل")
    if _national_id_taken(db, company_id, payload.national_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "الرقم القومي/الهوية مسجل لموظف آخر في هذه الشركة")
    _validate_user_link(db, company_id, payload.user_id)
    department_id = _validate_fk(db, company_id, payload.department_id, models.Department, "الإدارة")
    job_title_id = _validate_fk(db, company_id, payload.job_title_id, models.HrJobTitle, "المسمى الوظيفي")
    grade_id = _validate_fk(db, company_id, payload.grade_id, models.HrGrade, "الدرجة")
    branch_id = _validate_fk(db, company_id, payload.branch_id, models.Branch, "الفرع")
    manager_id = _validate_fk(db, company_id, payload.manager_id, models.HrEmployee, "المدير المباشر")
    if payload.basic_salary is not None and job_title_id:
        jt = db.get(models.HrJobTitle, job_title_id)
        if jt is not None and jt.max_salary is not None and payload.basic_salary > jt.max_salary:  # type: ignore[union-attr]
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الراتب يجاوز أقصى حد للمسمى الوظيفي")
    emp = models.HrEmployee(
        company_id=company_id,
        code=code,
        full_name=full_name,
        national_id=payload.national_id,
        gender=payload.gender,
        birth_date=payload.birth_date,
        nationality=payload.nationality,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        department_id=department_id,
        job_title_id=job_title_id,
        grade_id=grade_id,
        branch_id=branch_id,
        manager_id=manager_id,
        user_id=payload.user_id,
        hire_date=payload.hire_date or date.today(),
        basic_salary=payload.basic_salary,
        bank_account=payload.bank_account,
        status=payload.status,
        is_active=payload.status != "terminated",
    )
    db.add(emp)
    db.flush()
    _snapshot_move(
        db,
        emp,
        schemas.HrEmployeeMoveCreate(
            move_type="hire",  # type: ignore[arg-type]
            effective_date=emp.hire_date,  # type: ignore[arg-type]
            to_department_id=department_id,
            to_job_title_id=job_title_id,
            to_salary=payload.basic_salary,
            new_status=payload.status,  # type: ignore[arg-type]
            reason="مباشرة العمل",
        ),
        user,
    )
    audit(db, user, "create", "hr_employee", emp, f"{emp.code} · {emp.full_name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "بيانات الموظف مكررة (كود/رقم قومي) في هذه الشركة") from exc
    db.refresh(emp)
    return _employee_out(db, emp)


@router.patch("/employees/{employee_id}", response_model=schemas.HrEmployeeOut)
def update_employee(employee_id: int, payload: schemas.HrEmployeeUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    emp = _employee_or_404(db, employee_id)
    data = payload.model_dump(exclude_unset=True)
    before = {f: getattr(emp, f) for f in ("department_id", "job_title_id", "basic_salary", "status")}
    if "full_name" in data:
        new_name = (data["full_name"] or "").strip()
        if new_name and new_name != emp.full_name and (
            db.query(models.HrEmployee).filter(models.HrEmployee.company_id == db.info["company_id"], models.HrEmployee.full_name == new_name, models.HrEmployee.id != employee_id).first()
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, "اسم الموظف مستخدم بالفعل")
    if "national_id" in data and _national_id_taken(db, db.info["company_id"], data["national_id"], exclude_id=employee_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "الرقم القومي/الهوية مسجل لموظف آخر في هذه الشركة")
    for field, model, label in (
        ("department_id", models.Department, "الإدارة"),
        ("job_title_id", models.HrJobTitle, "المسمى الوظيفي"),
        ("grade_id", models.HrGrade, "الدرجة"),
        ("branch_id", models.Branch, "الفرع"),
        ("manager_id", models.HrEmployee, "المدير المباشر"),
    ):
        if field in data:
            data[field] = _validate_fk(db, db.info["company_id"], data[field], model, label)
    if "manager_id" in data and data["manager_id"] == employee_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لا يمكن أن يكون الموظف مديرًا لنفسه")
    if "user_id" in data:
        _validate_user_link(db, db.info["company_id"], data["user_id"], exclude_id=employee_id)
    for key, value in data.items():
        setattr(emp, key, value)
    if emp.status == "terminated":  # type: ignore[union-attr]
        emp.is_active = False  # type: ignore[assignment]
        if emp.terminated_at is None:  # type: ignore[union-attr]
            emp.terminated_at = date.today()  # type: ignore[assignment]
    elif emp.status in ("active", "probation"):  # type: ignore[union-attr]
        emp.is_active = True  # type: ignore[assignment]
    _auto_move(db, emp, before, user)
    audit(db, user, "update", "hr_employee", emp, f"{emp.code} · " + "، ".join(data.keys()))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "بيانات الموظف مكررة في هذه الشركة") from exc
    db.refresh(emp)
    return _employee_out(db, emp)


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(employee_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    emp = _employee_or_404(db, employee_id)
    if db.query(models.HrEmployee).filter(models.HrEmployee.company_id == db.info["company_id"], models.HrEmployee.manager_id == employee_id).count():
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن الحذف: هو مدير مباشر لموظفين آخرين — حدّد لهم مديرًا بديلًا أولاً")
    audit(db, user, "delete", "hr_employee", employee_id, f"{emp.code} · {emp.full_name}")
    db.delete(emp)
    db.commit()


# ------------------------------------------------------------------ contracts

@router.get("/employees/{employee_id}/contracts", response_model=List[schemas.HrContractOut])
def list_contracts(employee_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    emp = _employee_or_404(db, employee_id)
    return list(emp.contracts)


@router.post("/employees/{employee_id}/contracts", response_model=schemas.HrContractOut, status_code=status.HTTP_201_CREATED)
def create_contract(employee_id: int, payload: schemas.HrContractCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    emp = _employee_or_404(db, employee_id)
    if payload.kind != "unlimited" and payload.end_date is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "عقد محدد المدة/الإضافي يتطلب تاريخ نهاية")
    company_id = db.info["company_id"]
    code_base = (payload.code if hasattr(payload, "code") else None) or unique_code(db, models.HrContract, company_id, f"{emp.code}-CTR", "CTR")

    # إتراح العقود السابقة النشطة إن كانت العقد الجديد نشطًا
    if payload.status == "active":
        db.query(models.HrContract).filter(
            models.HrContract.company_id == company_id,
            models.HrContract.employee_id == emp.id,
            models.HrContract.status == "active",
        ).update({"status": "terminated"}, synchronize_session=False)

    contract = models.HrContract(
        company_id=company_id,
        employee_id=emp.id,
        code=code_base,
        kind=payload.kind,
        start_date=payload.start_date or date.today(),
        end_date=payload.end_date,
        basic_salary=payload.basic_salary,
        status=payload.status,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(contract)
    audit(db, user, "create", "hr_contract", contract, f"{emp.code} · {contract.code} · {contract.kind}")
    db.commit()
    db.refresh(contract)
    return contract


@router.patch("/contracts/{contract_id}", response_model=schemas.HrContractOut)
def update_contract(contract_id: int, payload: schemas.HrContractUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    contract = (
        db.query(models.HrContract)
        .filter(models.HrContract.company_id == db.info["company_id"], models.HrContract.id == contract_id)
        .one_or_none()
    )
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العقد غير موجود")
    data = payload.model_dump(exclude_unset=True)
    start = data.get("start_date") or contract.start_date
    end = data.get("end_date") or contract.end_date
    kind = data.get("kind") or contract.kind
    if kind != "unlimited" and end is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "عقد محدد المدة يتطلب تاريخ نهاية")
    if end is not None and start and end < start:  # type: ignore[operator]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "تاريخ النهاية يجب أن يكون بعد تاريخ البداية")
    for key, value in data.items():
        setattr(contract, key, value)
    audit(db, user, "update", "hr_contract", contract, f"{contract.code} · " + "، ".join(data.keys()))
    db.commit()
    db.refresh(contract)
    return contract


@router.delete("/contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(contract_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    contract = (
        db.query(models.HrContract)
        .filter(models.HrContract.company_id == db.info["company_id"], models.HrContract.id == contract_id)
        .one_or_none()
    )
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العقد غير موجود")
    audit(db, user, "delete", "hr_contract", contract_id, contract.code)
    db.delete(contract)
    db.commit()


# ------------------------------------------------------------------ documents

@router.get("/employees/{employee_id}/documents", response_model=List[schemas.HrDocumentOut])
def list_documents(employee_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    emp = _employee_or_404(db, employee_id)
    return [_document_out(d) for d in emp.documents]


@router.post("/employees/{employee_id}/documents", response_model=schemas.HrDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    employee_id: int,
    title: str = Form(...),
    doc_type: str = Form("other"),
    issue_date: Optional[date] = Form(None),
    expiry_date: Optional[date] = Form(None),
    notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_manager),
):
    emp = _employee_or_404(db, employee_id)
    if doc_type not in schemas._DOC_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نوع المستند غير مدعوم")
    file_name = None
    file_blob = None
    file_mime = None
    if file is not None and await file.read(1):
        await file.seek(0)
        data = await file.read()
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "حجم المستند يتجاوز 10 ميجابايت")
        mime = file.content_type or "application/octet-stream"
        if mime not in _ALLOWED_DOC_MIMES:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "نوع الملف غير مدعوم (PDF أو صورة أو مستند مكتبي)")
        file_name = file.filename
        file_blob = data
        file_mime = mime
    doc = models.HrDocument(
        company_id=db.info["company_id"],
        employee_id=emp.id,
        doc_type=doc_type,
        title=title.strip(),
        issue_date=issue_date,
        expiry_date=expiry_date,
        file_name=file_name,
        file_blob=file_blob,
        file_mime=file_mime,
        notes=notes,
        created_by=user.id,
    )
    db.add(doc)
    audit(db, user, "create", "hr_document", doc, f"{emp.code} · {doc.title}")
    db.commit()
    db.refresh(doc)
    return _document_out(doc)


@router.get("/documents/{doc_id}/file")
def download_document(doc_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    doc = (
        db.query(models.HrDocument)
        .filter(models.HrDocument.company_id == db.info["company_id"], models.HrDocument.id == doc_id)
        .one_or_none()
    )
    if doc is None or doc.file_blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ملف المستند غير موجود")
    media = doc.file_mime or "application/octet-stream"  # type: ignore[union-attr]
    return Response(content=doc.file_blob, media_type=media, headers={"Content-Disposition": f'attachment; filename="{doc.file_name or "document"}"'})


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    doc = (
        db.query(models.HrDocument)
        .filter(models.HrDocument.company_id == db.info["company_id"], models.HrDocument.id == doc_id)
        .one_or_none()
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستند غير موجود")
    audit(db, user, "delete", "hr_document", doc_id, doc.title)
    db.delete(doc)
    db.commit()


# ------------------------------------------------------------------ moves (السجل الوظيفي)

@router.get("/employees/{employee_id}/moves", response_model=List[schemas.HrEmployeeMoveOut])
def list_moves(employee_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    emp = _employee_or_404(db, employee_id)
    return list(emp.moves)


@router.post("/employees/{employee_id}/moves", response_model=schemas.HrEmployeeMoveOut, status_code=status.HTTP_201_CREATED)
def create_move(employee_id: int, payload: schemas.HrEmployeeMoveCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    emp = _employee_or_404(db, employee_id)
    move = _snapshot_move(db, emp, payload, user)
    audit(db, user, "update", "hr_employee", emp, f"{emp.code} · تطبيق {payload.move_type}")
    db.commit()
    db.refresh(move)
    db.refresh(emp)
    return move


# =====================================================================
# الوقت والإجازات (S2): ورديات، حضور، عطلات، أنواع إجازات، أرصدة، طلبات
# =====================================================================

def _hhmm_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _compute_attendance_metrics(
    shift: Optional[models.HrShift],
    status: str,
    check_in: Optional[str],
    check_out: Optional[str],
) -> tuple[int, int]:
    """يحسب (late_minutes, overtime_minutes) من الوردية المسندة للموظف إن وُجدت."""
    if status in ("absent", "excused") or not check_in or not shift or not check_out:
        return 0, 0
    start = _hhmm_minutes(shift.start_time)
    end = _hhmm_minutes(shift.end_time)
    cin = _hhmm_minutes(check_in)
    cout = _hhmm_minutes(check_out)
    if shift.cross_midnight:
        if cout <= cin:  # نهاية الوردية تقع بعد منتصف الليل
            cout += 1440
        if cin < start:  # دخول بعد منتصف الليل (الوردية بدأت البارحة)
            cin += 1440
        shift_length = (end - start) if end > start else (end - start + 1440)
        expected_end = start + shift_length
    else:
        expected_end = end
    late = max(0, cin - start - shift.grace_minutes)
    overtime = max(0, cout - expected_end)
    return late, overtime


def _leave_days(from_date: date, to_date: date) -> Decimal:
    return Decimal((to_date - from_date).days + 1).quantize(Decimal("0.1"))


def _ensure_leave_balance(
    db: Session,
    company_id: int,
    emp: models.HrEmployee,
    leave_type: models.HrLeaveType,
    year: int,
) -> models.HrLeaveBalance:
    balance = (
        db.query(models.HrLeaveBalance)
        .filter(
            models.HrLeaveBalance.company_id == company_id,
            models.HrLeaveBalance.employee_id == emp.id,
            models.HrLeaveBalance.leave_type_id == leave_type.id,
            models.HrLeaveBalance.year == year,
        )
        .one_or_none()
    )
    if balance is None:
        balance = models.HrLeaveBalance(
            company_id=company_id,
            employee_id=emp.id,
            leave_type_id=leave_type.id,
            year=year,
            entitled_days=leave_type.days_per_year,
            carried_days=Decimal("0"),
            used_days=Decimal("0"),
        )
        db.add(balance)
        db.flush()
    return balance


# ------------------------------------------------------------------ shifts

@router.get("/shifts", response_model=List[schemas.HrShiftOut])
def list_shifts(
    active_only: bool = False,
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrShift).filter(models.HrShift.company_id == db.info["company_id"])
    if active_only:
        q = q.filter(models.HrShift.is_active.is_(True))
    rows = q.order_by(models.HrShift.name).all()
    response.headers["X-Total-Count"] = str(len(rows))
    return rows


@router.post("/shifts", response_model=schemas.HrShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(payload: schemas.HrShiftCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    name = payload.name.strip()
    if db.query(models.HrShift).filter(models.HrShift.company_id == company_id, models.HrShift.name == name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "اسم الوردية مستخدم بالفعل")
    row = models.HrShift(
        company_id=company_id,
        name=name,
        start_time=payload.start_time,
        end_time=payload.end_time,
        grace_minutes=payload.grace_minutes,
        cross_midnight=payload.cross_midnight or _hhmm_minutes(payload.end_time) <= _hhmm_minutes(payload.start_time),
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "hr_shift", row, f"{row.name} · {row.start_time}-{row.end_time}")
    return row


@router.patch("/shifts/{shift_id}", response_model=schemas.HrShiftOut)
def update_shift(shift_id: int, payload: schemas.HrShiftUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrShift).filter(models.HrShift.company_id == db.info["company_id"], models.HrShift.id == shift_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الوردية غير موجودة")
    data = payload.model_dump(exclude_unset=True)
    name = (data.get("name") or row.name).strip()
    if (
        db.query(models.HrShift)
        .filter(models.HrShift.company_id == db.info["company_id"], models.HrShift.id != shift_id, models.HrShift.name == name)
        .first()
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "اسم الوردية مستخدم بالفعل")
    row.name = name
    row.start_time = data.get("start_time") or row.start_time
    row.end_time = data.get("end_time") or row.end_time
    row.grace_minutes = data.get("grace_minutes", row.grace_minutes)
    row.is_active = data.get("is_active", row.is_active)
    row.cross_midnight = data.get("cross_midnight") or _hhmm_minutes(row.end_time) <= _hhmm_minutes(row.start_time)
    audit(db, user, "update", "hr_shift", row, row.name)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/shifts/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift(shift_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrShift).filter(models.HrShift.company_id == db.info["company_id"], models.HrShift.id == shift_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الوردية غير موجودة")
    if db.query(models.HrShiftAssignment).filter(models.HrShiftAssignment.shift_id == row.id).count():
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن الحذف: الوردية مسندة لموظفين — أوقف تفعيلها بدلًا من ذلك")
    audit(db, user, "delete", "hr_shift", row.id, row.name)
    db.delete(row)
    db.commit()


@router.get("/shift-assignments", response_model=List[schemas.HrShiftAssignmentOut])
def list_shift_assignments(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return (
        db.query(models.HrShiftAssignment)
        .filter(models.HrShiftAssignment.company_id == db.info["company_id"])
        .order_by(models.HrShiftAssignment.id)
        .all()
    )


@router.post("/shift-assignments", response_model=List[schemas.HrShiftAssignmentOut], status_code=status.HTTP_201_CREATED)
def assign_shift(payload: schemas.HrShiftAssignmentSet, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """إسناد وردية لموظف (تستبدل الموجودة) أو إزالتها بتمرير shift_id=null."""
    company_id = db.info["company_id"]
    emp = _employee_or_404(db, payload.employee_id)
    existing = (
        db.query(models.HrShiftAssignment)
        .filter(models.HrShiftAssignment.company_id == company_id, models.HrShiftAssignment.employee_id == emp.id)
        .all()
    )
    for row in existing:
        db.delete(row)
    created: List[models.HrShiftAssignment] = []
    if payload.shift_id is not None:
        shift = db.get(models.HrShift, payload.shift_id)
        if shift is None or shift.company_id != company_id or not shift.is_active:  # type: ignore[union-attr]
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الوردية غير موجودة أو غير مفعلة في هذه الشركة")
        row = models.HrShiftAssignment(company_id=company_id, employee_id=emp.id, shift_id=shift.id, created_by=user.id)
        db.add(row)
        created.append(row)
    audit(db, user, "update", "hr_shift_assignment", emp, f"{emp.code} · وردية: {shift.name if payload.shift_id is not None else 'بدون'}")
    db.commit()
    for row in created:
        db.refresh(row)
    return created or db.query(models.HrShiftAssignment).filter(models.HrShiftAssignment.employee_id == emp.id).all()


# ------------------------------------------------------------------ attendance

def _attendance_metrics_for(db: Session, company_id: int, employee_id: int, status_value: str, check_in: Optional[str], check_out: Optional[str]) -> tuple[int, int]:
    assignment = (
        db.query(models.HrShiftAssignment)
        .filter(models.HrShiftAssignment.company_id == company_id, models.HrShiftAssignment.employee_id == employee_id)
        .one_or_none()
    )
    shift = assignment.shift if assignment else None
    return _compute_attendance_metrics(shift, status_value, check_in, check_out)


@router.get("/attendance", response_model=List[schemas.HrAttendanceOut])
def list_attendance(
    response: Response,
    employee_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    attendance_status: Optional[str] = None,
    work_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrAttendance).filter(models.HrAttendance.company_id == db.info["company_id"])
    if employee_id:
        q = q.filter(models.HrAttendance.employee_id == employee_id)
    if work_date:
        q = q.filter(models.HrAttendance.work_date == work_date)
    if date_from:
        q = q.filter(models.HrAttendance.work_date >= date_from)
    if date_to:
        q = q.filter(models.HrAttendance.work_date <= date_to)
    if attendance_status:
        q = q.filter(models.HrAttendance.status == attendance_status)
    rows = paginate(q, response, skip, limit, models.HrAttendance.work_date.desc(), models.HrAttendance.id.desc())
    return rows


@router.post("/attendance", response_model=schemas.HrAttendanceOut, status_code=status.HTTP_201_CREATED)
def create_attendance(payload: schemas.HrAttendanceCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    emp = db.get(models.HrEmployee, payload.employee_id)
    if emp is None or emp.company_id != company_id:  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الموظف غير موجود في هذه الشركة")
    if payload.status in ("present", "late") and not payload.check_in:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الحضور يتطلب وقت دخول — أو سجّل الحالة «غياب»")
    if payload.check_in and payload.check_out and payload.check_out < payload.check_in:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "وقت الخروج يجب أن يكون بعد الدخول (للورديات الليلية استخدم وردية بعبور منتصف الليل)")
    if db.query(models.HrAttendance).filter(
        models.HrAttendance.company_id == company_id,
        models.HrAttendance.employee_id == payload.employee_id,
        models.HrAttendance.work_date == payload.work_date,
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "يوجد سجل حضور لهذا الموظف في نفس اليوم — استخدم التعديل")
    late, overtime = _attendance_metrics_for(db, company_id, payload.employee_id, payload.status, payload.check_in, payload.check_out)
    row = models.HrAttendance(
        company_id=company_id,
        employee_id=payload.employee_id,
        work_date=payload.work_date,
        status=payload.status,
        check_in=payload.check_in,
        check_out=payload.check_out,
        late_minutes=late,
        overtime_minutes=overtime,
        overtime_type=payload.overtime_type or "day",
        overtime_approved=payload.overtime_approved,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(row)
    audit(
        db, user, "create", "hr_attendance", row,
        f"{emp.code} · {payload.work_date} · {row.status}" + (f" · تأخير {late}د" if late else "") + (f" · إضافي {overtime}د" if overtime else ""),
    )
    db.commit()
    db.refresh(row)
    return row


@router.patch("/attendance/{attendance_id}", response_model=schemas.HrAttendanceOut)
def update_attendance(attendance_id: int, payload: schemas.HrAttendanceUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = (
        db.query(models.HrAttendance)
        .filter(models.HrAttendance.company_id == db.info["company_id"], models.HrAttendance.id == attendance_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "سجل الحضور غير موجود")
    data = payload.model_dump(exclude_unset=True)
    row.status = data.get("status", row.status)  # type: ignore[assignment]
    row.check_in = data.get("check_in") or row.check_in  # type: ignore[assignment]
    row.check_out = data.get("check_out") or row.check_out  # type: ignore[assignment]
    row.notes = data.get("notes", row.notes)
    if "overtime_type" in data:
        row.overtime_type = data["overtime_type"]  # type: ignore[assignment]
    if "overtime_approved" in data:
        row.overtime_approved = data["overtime_approved"]  # type: ignore[assignment]
    late, overtime = _attendance_metrics_for(db, db.info["company_id"], row.employee_id, row.status, row.check_in, row.check_out)  # type: ignore[arg-type]
    row.late_minutes = late  # type: ignore[assignment]
    row.overtime_minutes = overtime  # type: ignore[assignment]
    audit(db, user, "update", "hr_attendance", row, f"تعديل حضور · {row.status} · تأخير {late}د · إضافي {overtime}د")
    db.commit()
    db.refresh(row)
    return row


@router.delete("/attendance/{attendance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attendance(attendance_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = (
        db.query(models.HrAttendance)
        .filter(models.HrAttendance.company_id == db.info["company_id"], models.HrAttendance.id == attendance_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "سجل الحضور غير موجود")
    audit(db, user, "delete", "hr_attendance", attendance_id, f"حذف سجل {row.work_date}")  # type: ignore[union-attr]
    db.delete(row)
    db.commit()


# ------------------------------------------------------------------ holidays

@router.get("/holidays", response_model=List[schemas.HrHolidayOut])
def list_holidays(
    year: Optional[int] = None,
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrHoliday).filter(models.HrHoliday.company_id == db.info["company_id"])
    if year:
        q = q.filter(func.extract("year", models.HrHoliday.holiday_date) == year)
    rows = q.order_by(models.HrHoliday.holiday_date).all()
    response.headers["X-Total-Count"] = str(len(rows))
    return rows


@router.post("/holidays", response_model=schemas.HrHolidayOut, status_code=status.HTTP_201_CREATED)
def create_holiday(payload: schemas.HrHolidayCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    if db.query(models.HrHoliday).filter(models.HrHoliday.company_id == company_id, models.HrHoliday.holiday_date == payload.holiday_date).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "توجد عطلة مسجلة في نفس التاريخ")
    row = models.HrHoliday(company_id=company_id, name=payload.name.strip(), holiday_date=payload.holiday_date, notes=payload.notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "hr_holiday", row, f"{row.name} · {row.holiday_date}")
    return row


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holiday(holiday_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrHoliday).filter(models.HrHoliday.company_id == db.info["company_id"], models.HrHoliday.id == holiday_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العطلة غير موجودة")
    audit(db, user, "delete", "hr_holiday", holiday_id, f"{row.name} · {row.holiday_date}")  # type: ignore[union-attr]
    db.delete(row)
    db.commit()


# ------------------------------------------------------------------ leave types

@router.get("/leave-types", response_model=List[schemas.HrLeaveTypeOut])
def list_leave_types(
    active_only: bool = False,
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrLeaveType).filter(models.HrLeaveType.company_id == db.info["company_id"])
    if active_only:
        q = q.filter(models.HrLeaveType.is_active.is_(True))
    rows = q.order_by(models.HrLeaveType.name).all()
    response.headers["X-Total-Count"] = str(len(rows))
    return rows


@router.post("/leave-types", response_model=schemas.HrLeaveTypeOut, status_code=status.HTTP_201_CREATED)
def create_leave_type(payload: schemas.HrLeaveTypeCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    name = payload.name.strip()
    if db.query(models.HrLeaveType).filter(models.HrLeaveType.company_id == company_id, models.HrLeaveType.name == name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "نوع الإجازة مستخدم بالفعل")
    row = models.HrLeaveType(
        company_id=company_id,
        name=name,
        days_per_year=payload.days_per_year,
        is_paid=payload.is_paid,
        carry_over_days=payload.carry_over_days,
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "hr_leave_type", row, f"{row.name} · {row.days_per_year} يوم/سنة")
    return row


@router.patch("/leave-types/{leave_type_id}", response_model=schemas.HrLeaveTypeOut)
def update_leave_type(leave_type_id: int, payload: schemas.HrLeaveTypeUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrLeaveType).filter(models.HrLeaveType.company_id == db.info["company_id"], models.HrLeaveType.id == leave_type_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "نوع الإجازة غير موجود")
    data = payload.model_dump(exclude_unset=True)
    name = (data.get("name") or row.name).strip()
    if (
        db.query(models.HrLeaveType)
        .filter(models.HrLeaveType.company_id == db.info["company_id"], models.HrLeaveType.id != leave_type_id, models.HrLeaveType.name == name)
        .first()
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "نوع الإجازة مستخدم بالفعل")
    row.name = name
    row.days_per_year = data.get("days_per_year", row.days_per_year)
    row.is_paid = data.get("is_paid", row.is_paid)
    row.carry_over_days = data.get("carry_over_days", row.carry_over_days)
    row.is_active = data.get("is_active", row.is_active)
    audit(db, user, "update", "hr_leave_type", row, row.name)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/leave-types/{leave_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_leave_type(leave_type_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrLeaveType).filter(models.HrLeaveType.company_id == db.info["company_id"], models.HrLeaveType.id == leave_type_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "نوع الإجازة غير موجود")
    used = db.query(models.HrLeaveRequest).filter(models.HrLeaveRequest.leave_type_id == row.id).count()
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن الحذف: يوجد طلبات إجازة بهذا النوع — أوقف تفعيله بدلًا من ذلك")
    audit(db, user, "delete", "hr_leave_type", row.id, row.name)
    db.delete(row)
    db.commit()


# ------------------------------------------------------------------ balances

@router.get("/leave-balances", response_model=List[schemas.HrLeaveBalanceOut])
def list_leave_balances(
    year: Optional[int] = None,
    employee_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """أرصدة الإجازات للسنة (الافتراضية سنة اليوم) — تنشأ للأذن لكل موظف نشط × نوع إجازة مفعّل."""
    company_id = db.info["company_id"]
    balance_year = year or date.today().year
    employees_q = db.query(models.HrEmployee).filter(
        models.HrEmployee.company_id == company_id,
        models.HrEmployee.is_active.is_(True),
    )
    if employee_id:
        employees_q = employees_q.filter(models.HrEmployee.id == employee_id)
    leave_types = (
        db.query(models.HrLeaveType)
        .filter(models.HrLeaveType.company_id == company_id, models.HrLeaveType.is_active.is_(True))
        .order_by(models.HrLeaveType.name)
        .all()
    )
    for emp in employees_q.all():
        for lt_model in leave_types:
            _ensure_leave_balance(db, company_id, emp, lt_model, balance_year)
    # الالتزام هنا مباشرة: الكائنات الجديدة تخرج من db.new بعد flush الداخلي
    # لـ _ensure_leave_balance، فلا يُثبت وجودها إلا بـ commit صريح.
    db.commit()
    rows = (
        db.query(models.HrLeaveBalance)
        .filter(models.HrLeaveBalance.company_id == company_id, models.HrLeaveBalance.year == balance_year)
        .order_by(models.HrLeaveBalance.employee_id, models.HrLeaveBalance.leave_type_id)
        .all()
    )
    if employee_id:
        rows = [r for r in rows if r.employee_id == employee_id]
    return rows


@router.patch("/leave-balances/{balance_id}", response_model=schemas.HrLeaveBalanceOut)
def adjust_leave_balance(balance_id: int, payload: schemas.HrLeaveBalanceAdjust, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrLeaveBalance).filter(models.HrLeaveBalance.company_id == db.info["company_id"], models.HrLeaveBalance.id == balance_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الرصيد غير موجود")
    data = payload.model_dump(exclude_unset=True)
    row.entitled_days = data.get("entitled_days", row.entitled_days)  # type: ignore[assignment]
    row.carried_days = data.get("carried_days", row.carried_days)  # type: ignore[assignment]
    audit(db, user, "update", "hr_leave_balance", row, f"تعديل رصيد · مُستحق {row.entitled_days} · مُرحَّل {row.carried_days}")
    db.commit()
    db.refresh(row)
    return row


# ------------------------------------------------------------------ leave requests

def _check_leave_overlap(
    db: Session,
    company_id: int,
    employee_id: int,
    from_date: date,
    to_date: date,
    exclude_request_id: Optional[int] = None,
) -> None:
    """يرفض التعارض مع أي طلب معلّق/معتمد لنفس الموظف يغطي أيًّا من الأيام نفسها."""
    q = db.query(models.HrLeaveRequest).filter(
        models.HrLeaveRequest.company_id == company_id,
        models.HrLeaveRequest.employee_id == employee_id,
        models.HrLeaveRequest.status.in_(("pending", "approved")),
        models.HrLeaveRequest.from_date <= to_date,
        models.HrLeaveRequest.to_date >= from_date,
    )
    if exclude_request_id:
        q = q.filter(models.HrLeaveRequest.id != exclude_request_id)
    if q.first():
        raise HTTPException(status.HTTP_409_CONFLICT, "تعارض مع طلب إجازة آخر لنفس الموظف في نفس الفترة")


@router.get("/leave-requests", response_model=List[schemas.HrLeaveRequestOut])
def list_leave_requests(
    response: Response,
    employee_id: Optional[int] = None,
    request_status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrLeaveRequest).filter(models.HrLeaveRequest.company_id == db.info["company_id"])
    if employee_id:
        q = q.filter(models.HrLeaveRequest.employee_id == employee_id)
    if request_status:
        q = q.filter(models.HrLeaveRequest.status == request_status)
    rows = paginate(q, response, skip, limit, models.HrLeaveRequest.id.desc())
    return rows


@router.post("/leave-requests", response_model=schemas.HrLeaveRequestOut, status_code=status.HTTP_201_CREATED)
def create_leave_request(payload: schemas.HrLeaveRequestCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    emp = db.get(models.HrEmployee, payload.employee_id)
    if emp is None or emp.company_id != company_id or not emp.is_active:  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الموظف غير موجود أو غير نشط في هذه الشركة")
    leave_type = db.get(models.HrLeaveType, payload.leave_type_id)
    if leave_type is None or leave_type.company_id != company_id or not leave_type.is_active:  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نوع الإجازة غير موجود أو غير مفعّل في هذه الشركة")
    if payload.to_date < payload.from_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "تاريخ النهاية يجب أن يكون بعد تاريخ البداية")
    _check_leave_overlap(db, company_id, payload.employee_id, payload.from_date, payload.to_date)
    row = models.HrLeaveRequest(
        company_id=company_id,
        employee_id=payload.employee_id,
        leave_type_id=payload.leave_type_id,
        from_date=payload.from_date,
        to_date=payload.to_date,
        days=_leave_days(payload.from_date, payload.to_date),
        reason=payload.reason,
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_leave_request", row, f"{emp.code} · {leave_type.name} · {row.days} يوم")
    db.commit()
    db.refresh(row)
    return row


def _decided_leave_request_out(row: models.HrLeaveRequest) -> schemas.HrLeaveRequestOut:
    return schemas.HrLeaveRequestOut.model_validate(row)


@router.post("/leave-requests/{request_id}/approve", response_model=schemas.HrLeaveRequestOut)
def approve_leave_request(request_id: int, payload: schemas.HrLeaveDecision, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = (
        db.query(models.HrLeaveRequest)
        .filter(models.HrLeaveRequest.company_id == db.info["company_id"], models.HrLeaveRequest.id == request_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "طلب الإجازة غير موجود")
    if row.status != "pending":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, f"لا يمكن الموافقة: حالة الطلب «{row.status}»")  # type: ignore[union-attr]
    company_id = db.info["company_id"]

    # مسار الموافقات متعدد المستويات: إن وُجد مسار للإجازات يمشي الطلب مستوى بمستوى.
    chain = (
        db.query(models.HrApprovalChain)
        .filter(models.HrApprovalChain.company_id == company_id, models.HrApprovalChain.entity_type == "leave")
        .order_by(models.HrApprovalChain.level)
        .all()
    )
    if chain:
        next_level = int(row.approval_level or 0) + 1  # type: ignore[union-attr]
        entry = next((c for c in chain if c.level == next_level), None)
        if entry is not None:
            authorized = (
                user.is_platform_admin
                or user_role(user) == "admin"
                or (entry.approver_user_id == user.id)
                or (entry.approver_role is not None and user_role(user) == entry.approver_role)
            )
            if not authorized:
                required_name = entry.approver.username if entry.approver else (entry.approver_role or "—")
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"المستوى {next_level} من مسار الموافقات يتطلب موافقة: {required_name}",
                )
            db.add(models.HrApprovalStep(
                company_id=company_id, entity_type="leave", entity_id=row.id,
                level=next_level, approver_user_id=user.id, decision="approved", notes=payload.decision_note,
            ))
            if any(c.level > next_level for c in chain):
                # ليس آخر مستوى — يبقى قيد الموافقة على المستوى التالي
                row.approval_level = next_level  # type: ignore[assignment]
                audit(db, user, "update", "hr_leave_request", row, f"موافقة المستوى {next_level}/{len(chain)} — بانتظار المستوى التالي")
                db.commit()
                db.refresh(row)
                return _decided_leave_request_out(row)
            # آخر مستوى: استكمال الاعتماد النهائي
            row.approval_level = next_level  # type: ignore[assignment]

    leave_type = db.get(models.HrLeaveType, row.leave_type_id)  # type: ignore[arg-type]
    balance = _ensure_leave_balance(db, company_id, row.employee, leave_type, row.from_date.year)  # type: ignore[arg-type]
    if balance.remaining_days < row.days:  # type: ignore[operator]
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"الرصيد لا يكفي: المتبقي {balance.remaining_days} يوم والطلب {row.days} يوم — عدّل الرصيد أو ارفض الطلب",
        )
    _check_leave_overlap(db, company_id, row.employee_id, row.from_date, row.to_date, exclude_request_id=row.id)  # type: ignore[arg-type]
    balance.used_days = (Decimal(balance.used_days or 0) + Decimal(row.days)).quantize(Decimal("0.1"))  # type: ignore[operator]
    row.status = "approved"  # type: ignore[assignment]
    row.decision_note = payload.decision_note  # type: ignore[assignment]
    row.decided_by = user.id
    row.decided_at = func.now()
    audit(db, user, "update", "hr_leave_request", row, f"موافقة · {row.days} يوم · رصيد بعد: {balance.remaining_days}")
    db.commit()
    db.refresh(row)
    return _decided_leave_request_out(row)


@router.post("/leave-requests/{request_id}/reject", response_model=schemas.HrLeaveRequestOut)
def reject_leave_request(request_id: int, payload: schemas.HrLeaveDecision, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = (
        db.query(models.HrLeaveRequest)
        .filter(models.HrLeaveRequest.company_id == db.info["company_id"], models.HrLeaveRequest.id == request_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "طلب الإجازة غير موجود")
    if row.status != "pending":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, f"لا يمكن الرفض: حالة الطلب «{row.status}»")  # type: ignore[union-attr]
    db.add(models.HrApprovalStep(
        company_id=db.info["company_id"], entity_type="leave", entity_id=row.id,
        level=int(row.approval_level or 0) + 1, approver_user_id=user.id, decision="rejected", notes=payload.decision_note,
    ))
    row.status = "rejected"  # type: ignore[assignment]
    row.decision_note = payload.decision_note  # type: ignore[assignment]
    row.decided_by = user.id
    row.decided_at = func.now()
    audit(db, user, "update", "hr_leave_request", row, "رفض الطلب")
    db.commit()
    db.refresh(row)
    return _decided_leave_request_out(row)


@router.post("/leave-requests/{request_id}/cancel", response_model=schemas.HrLeaveRequestOut)
def cancel_leave_request(request_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = (
        db.query(models.HrLeaveRequest)
        .filter(models.HrLeaveRequest.company_id == db.info["company_id"], models.HrLeaveRequest.id == request_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "طلب الإجازة غير موجود")
    if row.status not in ("pending", "approved"):  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, f"لا يمكن الإلغاء: حالة الطلب «{row.status}»")  # type: ignore[union-attr]
    if row.status == "approved":  # type: ignore[union-attr]
        # إلغاء إجازة معتمدة يعيد أيامها للرصيد
        balance = _ensure_leave_balance(db, db.info["company_id"], row.employee, db.get(models.HrLeaveType, row.leave_type_id), row.from_date.year)  # type: ignore[arg-type]
        balance.used_days = max(Decimal("0"), Decimal(balance.used_days or 0) - Decimal(row.days)).quantize(Decimal("0.1"))  # type: ignore[operator]
    row.status = "cancelled"  # type: ignore[assignment]
    row.decided_by = user.id
    row.decided_at = func.now()
    audit(db, user, "update", "hr_leave_request", row, "إلغاء الطلب")
    db.commit()
    db.refresh(row)
    return _decided_leave_request_out(row)


# =====================================================================
# الرواتب (S3): مكونات راتب لكل موظف + مسيرات شهرية بترحيل محاسبي
# =====================================================================

_PAYROLL_PAYABLE_CODE = "2140"  # رواتب مستحقة
_PAYROLL_ACCRUED_CODE = "2120"  # خصومات محتجزة تحت مصاريف مستحقة


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """أول وآخر يوم في الشهر الميلادي."""
    last = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return date(year, month, 1), last


def _employee_base_salary(emp: models.HrEmployee) -> Decimal:
    """الراتب الأساسي: راتب عقد نشط إن وُجد وإلا أساسي الموظف."""
    contract_salary = None
    for contract in getattr(emp, "contracts", []):
        if contract.status == "active":
            contract_salary = contract.basic_salary
            break
    return Decimal(contract_salary or emp.basic_salary or 0)


def _component_value(component: models.HrSalaryComponent, base_salary: Decimal) -> Decimal:
    """قيمة مكوّن شهري: مبلغ ثابت أو نسبة من الراتب الأساسي."""
    if component.amount_mode == "percent_of_base":
        return (base_salary * Decimal(component.percent_value or 0) / Decimal("100")).quantize(Decimal("0.01"))
    return Decimal(component.fixed_amount or 0).quantize(Decimal("0.01"))


def _overlap_days(a_from: date, a_to: date, b_from: date, b_to: date) -> int:
    """عدد الأيام المتقاطعة بين فترتين (شامل الطرفين)."""
    start = max(a_from, b_from)
    end = min(a_to, b_to)
    return max(0, (end - start).days + 1)


def _advance_installment_due(db: Session, adv: models.HrAdvance, year: int, month: int) -> Optional[Decimal]:
    """قسط السلفة المستحق لشهر المسير (None لخارجه) — لا يتجاوز المتبقي المخصوم فعلاً."""
    months_in = (year - adv.start_year) * 12 + month - adv.start_month + 1
    if months_in < 1 or months_in > adv.installments_count:
        return None
    consumed = (
        db.query(func.coalesce(func.sum(models.HrPayslipLine.amount), 0))
        .filter(models.HrPayslipLine.advance_id == adv.id)
        .scalar()
    )
    remaining = Decimal(adv.amount) - Decimal(consumed)
    if remaining <= 0:
        return None
    installment = (Decimal(adv.amount) / adv.installments_count).quantize(Decimal("0.01"))
    return min(installment, remaining).quantize(Decimal("0.01"))


def _generate_payslip(
    db: Session,
    company_id: int,
    run: models.HrPayrollRun,
    emp: models.HrEmployee,
    m_from: date,
    m_to: date,
    unpaid_type_ids: set[int],
) -> models.HrPayslip:
    """يبني قسيمة راتب موظف: الأساسي + الربح − الخصوم − غياب/إجازة غير مدفوعة."""
    base_salary = _employee_base_salary(emp)
    absent_days = (
        db.query(models.HrAttendance)
        .filter(
            models.HrAttendance.company_id == company_id,
            models.HrAttendance.employee_id == emp.id,
            models.HrAttendance.status == "absent",
            models.HrAttendance.work_date >= m_from,
            models.HrAttendance.work_date <= m_to,
        )
        .count()
    )
    days_in_month = (m_to - m_from).days + 1
    daily_rate = (base_salary / days_in_month).quantize(Decimal("0.01"))

    # أيام الإجازات غير المدفوعة المعتمدة المتقاطعة مع الشهر
    unpaid_leave_days = Decimal("0")
    if unpaid_type_ids:
        unpaid_reqs = (
            db.query(models.HrLeaveRequest)
            .filter(
                models.HrLeaveRequest.company_id == company_id,
                models.HrLeaveRequest.employee_id == emp.id,
                models.HrLeaveRequest.status == "approved",
                models.HrLeaveRequest.leave_type_id.in_(unpaid_type_ids),
                models.HrLeaveRequest.from_date <= m_to,
                models.HrLeaveRequest.to_date >= m_from,
            )
            .all()
        )
        for req in unpaid_reqs:
            unpaid_leave_days += Decimal(_overlap_days(req.from_date, req.to_date, m_from, m_to))

    absence_deduction = (daily_rate * Decimal(absent_days + unpaid_leave_days)).quantize(Decimal("0.01"))

    slip = models.HrPayslip(
        company_id=company_id,
        run_id=run.id,
        employee_id=emp.id,
        base_salary=base_salary,
        absent_days=absent_days,
        unpaid_leave_days=unpaid_leave_days,
        absence_deduction=absence_deduction,
        total_earnings=Decimal("0"),
        total_deductions=Decimal("0"),
        net_pay=Decimal("0"),
    )
    db.add(slip)
    db.flush()

    # السطور المجمدة: الأساسي + المكونات + خصم الغياب
    earnings = Decimal("0")
    db.add(models.HrPayslipLine(
        company_id=company_id, payslip_id=slip.id, category="earning",
        name="الراتب الأساسي", amount=base_salary,
    ))
    components = (
        db.query(models.HrSalaryComponent)
        .filter(
            models.HrSalaryComponent.company_id == company_id,
            models.HrSalaryComponent.employee_id == emp.id,
            models.HrSalaryComponent.is_active.is_(True),
        )
        .order_by(models.HrSalaryComponent.category, models.HrSalaryComponent.id)
        .all()
    )
    for comp in components:
        value = _component_value(comp, base_salary)
        if value == 0:
            continue
        line_cat = "earning" if comp.category == "earning" else "deduction"
        db.add(models.HrPayslipLine(
            company_id=company_id, payslip_id=slip.id, category=line_cat,
            name=comp.name, amount=value,
        ))
        if line_cat == "earning":
            earnings += value
        else:
            slip.total_deductions = Decimal(slip.total_deductions) + value

    # أقساط السلف المستحقة لشهر هذا المسير (لا تتجاوز المتبقي من كل سلفة)
    advances = (
        db.query(models.HrAdvance)
        .filter(
            models.HrAdvance.company_id == company_id,
            models.HrAdvance.employee_id == emp.id,
            models.HrAdvance.status == "active",
        )
        .order_by(models.HrAdvance.id)
        .all()
    )
    for adv in advances:
        due = _advance_installment_due(db, adv, run.year, run.month)
        if due is None:
            continue
        db.add(models.HrPayslipLine(
            company_id=company_id, payslip_id=slip.id, category="deduction",
            name=f"قسط سلفة {adv.advance_code}", amount=due, advance_id=adv.id,
            notes=f"{adv.amount} على {adv.installments_count} قسطاً",
        ))
        slip.total_deductions = Decimal(slip.total_deductions) + due

    # ساعات العمل الإضافي المعتمدة خلال فترة هذا المسير
    overtime_records = (
        db.query(models.HrAttendance)
        .filter(
            models.HrAttendance.company_id == company_id,
            models.HrAttendance.employee_id == emp.id,
            models.HrAttendance.work_date >= m_from,
            models.HrAttendance.work_date <= m_to,
            models.HrAttendance.overtime_minutes > 0,
            models.HrAttendance.overtime_approved.is_(True),
        )
        .all()
    )
    if overtime_records:
        # حساب أجر الساعة القياسي: الراتب الأساسي / (أيام الشهر × 8 ساعات)
        hourly_rate = (daily_rate / Decimal("8")).quantize(Decimal("0.01"))
        total_ot_pay = Decimal("0")
        total_ot_mins = 0
        multipliers = {
            "day": Decimal("1.35"),      # إضافي نهاري (ساعة + 35%)
            "night": Decimal("1.70"),    # إضافي ليلي (ساعة + 70%)
            "holiday": Decimal("2.00"),  # إضافي عطلات ومناسبات (مثلي الأجر)
        }
        for rec in overtime_records:
            ot_mins = rec.overtime_minutes or 0
            total_ot_mins += ot_mins
            ot_hours = Decimal(str(ot_mins)) / Decimal("60")
            mult = multipliers.get(rec.overtime_type or "day", Decimal("1.35"))
            total_ot_pay += (ot_hours * hourly_rate * mult)

        total_ot_pay = total_ot_pay.quantize(Decimal("0.01"))
        if total_ot_pay > 0:
            ot_hours_display = round(total_ot_mins / 60, 1)
            db.add(models.HrPayslipLine(
                company_id=company_id, payslip_id=slip.id, category="earning",
                name=f"ساعات عمل إضافية ({ot_hours_display} س)", amount=total_ot_pay,
            ))
            earnings += total_ot_pay

    deductions = Decimal(slip.total_deductions)
    if absence_deduction > 0:
        db.add(models.HrPayslipLine(
            company_id=company_id, payslip_id=slip.id, category="absence",
            name=f"خصم غياب ({absent_days} يوم) / إجازة غير مدفوعة ({unpaid_leave_days} يوم)",
            amount=absence_deduction,
        ))
        deductions += absence_deduction
    slip.total_earnings = earnings
    slip.total_deductions = deductions
    slip.net_pay = (Decimal(base_salary) + earnings - deductions).quantize(Decimal("0.01"))
    # الجلسات بـ autoflush=False (اختبارات/توليد) — الالتزام هنا يضمن أن حساب
    # إجماليات المسير لاحقاً بلغة SQL يرَا القيم النهائية.
    db.flush()
    return slip


def _recompute_run_totals(db: Session, run: models.HrPayrollRun) -> None:
    rows = (
        db.query(
            func.count(models.HrPayslip.id),
            func.coalesce(func.sum(models.HrPayslip.base_salary) + func.sum(models.HrPayslip.total_earnings), 0),
            func.coalesce(func.sum(models.HrPayslip.total_deductions), 0),
            func.coalesce(func.sum(models.HrPayslip.net_pay), 0),
        )
        .filter(models.HrPayslip.run_id == run.id)
        .one()
    )
    run.employees_count = rows[0]
    run.total_gross = Decimal(rows[1]).quantize(Decimal("0.01"))
    run.total_deductions = Decimal(rows[2]).quantize(Decimal("0.01"))
    run.total_net = Decimal(rows[3]).quantize(Decimal("0.01"))


def _regenerate_run(db: Session, company_id: int, run: models.HrPayrollRun) -> None:
    """تفريغ وإعادة توليد بايسليبات المسير (مسودّة فقط) ببيانات الحضور/الإجازات الحالية."""
    db.query(models.HrPayslipLine).filter(
        models.HrPayslipLine.payslip_id.in_(db.query(models.HrPayslip.id).filter(models.HrPayslip.run_id == run.id))
    ).delete(synchronize_session=False)
    db.query(models.HrPayslip).filter(models.HrPayslip.run_id == run.id).delete(synchronize_session=False)
    db.flush()

    m_from, m_to = _month_bounds(run.year, run.month)
    unpaid_ids = {
        lt.id for lt in db.query(models.HrLeaveType)
        .filter(models.HrLeaveType.company_id == company_id, models.HrLeaveType.is_paid.is_(False))
        .all()
    }
    employees = (
        db.query(models.HrEmployee)
        .filter(models.HrEmployee.company_id == company_id, models.HrEmployee.is_active.is_(True))
        .order_by(models.HrEmployee.id)
        .all()
    )
    for emp in employees:
        if _employee_base_salary(emp) <= 0:
            continue  # موظف بلا راتب معروف: لا قسيمة
        _generate_payslip(db, company_id, run, emp, m_from, m_to, unpaid_ids)
    _recompute_run_totals(db, run)


@router.get("/salary-components", response_model=List[schemas.HrSalaryComponentOut])
def list_salary_components(
    employee_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrSalaryComponent).filter(models.HrSalaryComponent.company_id == db.info["company_id"])
    if employee_id:
        q = q.filter(models.HrSalaryComponent.employee_id == employee_id)
    return q.order_by(models.HrSalaryComponent.employee_id, models.HrSalaryComponent.category, models.HrSalaryComponent.id).all()


@router.post("/salary-components", response_model=schemas.HrSalaryComponentOut, status_code=status.HTTP_201_CREATED)
def create_salary_component(payload: schemas.HrSalaryComponentCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    emp = _employee_or_404(db, payload.employee_id)
    name = payload.name.strip()
    if db.query(models.HrSalaryComponent).filter(
        models.HrSalaryComponent.company_id == company_id,
        models.HrSalaryComponent.employee_id == emp.id,
        models.HrSalaryComponent.name == name,
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "اسم المكوّن مستخدم بالفعل لهذا الموظف")
    if payload.amount_mode == "fixed" and payload.fixed_amount is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "المكوّن الثابت يتطلب قيمة المبلغ")
    if payload.amount_mode == "percent_of_base" and payload.percent_value is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "مكوّن النسبة يتطلب قيمة النسبة المئوية")
    row = models.HrSalaryComponent(
        company_id=company_id,
        employee_id=emp.id,
        category=payload.category,
        name=name,
        amount_mode=payload.amount_mode,
        fixed_amount=payload.fixed_amount,
        percent_value=payload.percent_value,
        is_active=payload.is_active,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "hr_salary_component", row, f"{emp.code} · {row.name} · {row.category}")
    return row


@router.patch("/salary-components/bulk", response_model=schemas.HrSalaryComponentBulkOut)
def bulk_update_salary_components(payload: schemas.HrSalaryComponentBulkIn, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """تحديث جماعي لبند راتب باسم محدد على كل الموظفين — لتعديل نسب التأمينات/الضريبة بعد البذر من مكان واحد."""
    company_id = db.info["company_id"]
    base = db.query(models.HrSalaryComponent).filter(
        models.HrSalaryComponent.company_id == company_id,
        models.HrSalaryComponent.name == payload.name.strip(),
        models.HrSalaryComponent.category == payload.category,
    )
    count = base.count()
    updates: dict = {}
    if payload.percent_value is not None:
        updates["percent_value"] = payload.percent_value
    if payload.is_active is not None:
        updates["is_active"] = payload.is_active
    if updates and count:
        base.update(updates, synchronize_session=False)
    audit(db, user, "update", "hr_salary_component_bulk", None, f"تحديث جماعي «{payload.name}»: {count} بند · {updates}")
    db.commit()
    return schemas.HrSalaryComponentBulkOut(updated_count=int(count if updates else 0))


@router.patch("/salary-components/{component_id}", response_model=schemas.HrSalaryComponentOut)
def update_salary_component(component_id: int, payload: schemas.HrSalaryComponentUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrSalaryComponent).filter(models.HrSalaryComponent.company_id == db.info["company_id"], models.HrSalaryComponent.id == component_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المكوّن غير موجود")
    data = payload.model_dump(exclude_unset=True)
    if data.get("amount_mode") == "fixed" and data.get("fixed_amount") is None and row.fixed_amount is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "المكوّن الثابت يتطلب قيمة المبلغ")
    if data.get("amount_mode") == "percent_of_base" and data.get("percent_value") is None and row.percent_value is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "مكوّن النسبة يتطلب قيمة النسبة")
    for field, value in data.items():
        setattr(row, field, value)
    audit(db, user, "update", "hr_salary_component", row, row.name)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/salary-components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_salary_component(component_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = db.query(models.HrSalaryComponent).filter(models.HrSalaryComponent.company_id == db.info["company_id"], models.HrSalaryComponent.id == component_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المكوّن غير موجود")
    audit(db, user, "delete", "hr_salary_component", row.id, f"{row.name}")  # type: ignore[union-attr]
    db.delete(row)
    db.commit()


@router.get("/payroll-runs", response_model=List[schemas.HrPayrollRunOut])
def list_payroll_runs(
    response: Response,
    run_status: Optional[str] = None,
    year: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrPayrollRun).filter(models.HrPayrollRun.company_id == db.info["company_id"])
    if run_status:
        q = q.filter(models.HrPayrollRun.status == run_status)
    if year:
        q = q.filter(models.HrPayrollRun.year == year)
    return paginate(q, response, skip, limit, models.HrPayrollRun.year.desc(), models.HrPayrollRun.month.desc(), models.HrPayrollRun.id.desc())


@router.post("/payroll-runs", response_model=schemas.HrPayrollRunOut, status_code=status.HTTP_201_CREATED)
def create_payroll_run(payload: schemas.HrPayrollRunCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """إنشاء مسير شهري مسودّة وتوليد القسائم تلقائياً (الشهر مرفوق إن وُجد)."""
    company_id = db.info["company_id"]
    if db.query(models.HrPayrollRun).filter(
        models.HrPayrollRun.company_id == company_id, models.HrPayrollRun.year == payload.year, models.HrPayrollRun.month == payload.month
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"يوجد مسير للشهر {payload.year}-{int(payload.month):02d} بالفعل")
    run = models.HrPayrollRun(
        company_id=company_id,
        year=payload.year,
        month=payload.month,
        note=payload.note,
        created_by=user.id,
    )
    db.add(run)
    db.flush()
    _regenerate_run(db, company_id, run)
    audit(db, user, "create", "hr_payroll_run", run, f"مسير {run.period_label} · {run.employees_count} موظف · صافي {run.total_net}")
    db.commit()
    db.refresh(run)
    return run


@router.post("/payroll-runs/{run_id}/recalculate", response_model=schemas.HrPayrollRunOut)
def recalculate_payroll_run(run_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """إعادة توليد القسائم من الحضور/الإجازات/المكوّنات الحالية (مسودّة فقط)."""
    run = db.query(models.HrPayrollRun).filter(models.HrPayrollRun.company_id == db.info["company_id"], models.HrPayrollRun.id == run_id).one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسير غير موجود")
    if run.status != "draft":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, "المسير مُرحَّل — لا يمكن إعادة حسابه")
    _regenerate_run(db, db.info["company_id"], run)
    audit(db, user, "update", "hr_payroll_run", run, f"إعادة حساب {run.period_label} · صافي {run.total_net}")  # type: ignore[union-attr]
    db.commit()
    db.refresh(run)
    return run


@router.post("/payroll-runs/{run_id}/post", response_model=schemas.HrPayrollRunOut)
def post_payroll_run(run_id: int, payload: schemas.HrPayrollRunPost, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """ترحيل المسير: يقفل القسائم وينشئ قيداً متوازناً في دفتر الأستاذ.

    مدين مصروف الرواتب (5210) بمجموع المستحق، دائن رواتب مستحقة (2140) بالصافي،
    ودائن مصاريف مستحقة (2120) بقيمة الخصومات المحتجزة غير الغياب.
    """
    company_id = db.info["company_id"]
    run = db.query(models.HrPayrollRun).filter(models.HrPayrollRun.company_id == company_id, models.HrPayrollRun.id == run_id).one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسير غير موجود")
    if run.status != "draft":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, "المسير مُرحَّل بالفعل")
    if run.total_net == 0 and run.total_gross == 0:  # type: ignore[operator]
        raise HTTPException(422, "المسير فارغ (لا موظف براتب) — لا يُرحَّل")

    from ..accounting import AccountingEngine, seed_default_coa
    seed_default_coa(db, company_id)

    expense = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == "5210").first()
    payable = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == _PAYROLL_PAYABLE_CODE).first()
    if not expense or not payable:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "حسابات الرواتب (5210/2140) غير موجودة — هيّئ شجرة الحسابات أولًا")
    total_gross = Decimal(run.total_gross)  # type: ignore[arg-type]
    total_net = Decimal(run.total_net)  # type: ignore[arg-type]
    # خصم الغياب يخفّض المصروف نفسه (لا يستحق لأي جهة)؛ أما الخصومات
    # المحتجزة من الموظف فتبعد مستحقة لطرفها (تأمينات/تأمين…) في 2120.
    absence_total = Decimal(
        db.query(func.coalesce(func.sum(models.HrPayslip.absence_deduction), 0)).filter(models.HrPayslip.run_id == run.id).scalar()
    ).quantize(Decimal("0.01"))
    withheld = (Decimal(run.total_deductions) - absence_total).quantize(Decimal("0.01"))  # type: ignore[arg-type]
    expense_amount = (total_gross - absence_total).quantize(Decimal("0.01"))
    items: List[dict] = []
    if expense_amount > 0:
        items.append({"account_id": expense.id, "debit": expense_amount, "credit": Decimal("0"), "notes": f"مسير {run.period_label}"})
    if total_net > 0:
        items.append({"account_id": payable.id, "debit": Decimal("0"), "credit": total_net, "notes": "رواتب مستحقة"})
    if withheld > 0:
        accrued = db.query(models.ChartAccount).filter(models.ChartAccount.company_id == company_id, models.ChartAccount.code == _PAYROLL_ACCRUED_CODE).first()
        if not accrued:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "حساب الخصومات المحتجزة (2120) غير موجود — هيّئ شجرة الحسابات أولًا")
        items.append({"account_id": accrued.id, "debit": Decimal("0"), "credit": withheld, "notes": "خصومات محتجزة"})
    entry = AccountingEngine.create_entry(
        db=db, company_id=company_id, user_id=user.id,
        description=f"مسير رواتب {run.period_label}",
        items=items,
        reference=f"HR-PAY-{run.id}",
    )
    db.flush()
    run.status = "posted"  # type: ignore[assignment]
    run.journal_entry_id = entry.id  # type: ignore
    run.posted_by = user.id
    if payload.note and not run.note:  # type: ignore[union-attr]
        run.note = payload.note  # type: ignore[assignment]
    audit(db, user, "post", "hr_payroll_run", run, f"ترحيل {run.period_label} · صافي {total_net} · قيد #{entry.id}")  # type: ignore[union-attr]
    db.commit()
    db.refresh(run)
    return run


@router.delete("/payroll-runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payroll_run(run_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """حذف مسير مسودّة فقط؛ المُرحّل يتطلب أثراً محاسـبياً ولا يُحذف."""
    run = db.query(models.HrPayrollRun).filter(models.HrPayrollRun.company_id == db.info["company_id"], models.HrPayrollRun.id == run_id).one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسير غير موجود")
    if run.status != "draft":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, "المسير مُرحَّل — مرتبط بقيد محاسبي ولا يُحذف")
    audit(db, user, "delete", "hr_payroll_run", run.id, f"مسير {run.period_label}")  # type: ignore[union-attr]
    db.delete(run)
    db.commit()


@router.get("/payroll-runs/{run_id}/payslips", response_model=List[schemas.HrPayslipOut])
def list_run_payslips(
    run_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_permission_or_role("hr.payslip.view", "admin", "manager")),
):
    run = db.query(models.HrPayrollRun).filter(models.HrPayrollRun.company_id == db.info["company_id"], models.HrPayrollRun.id == run_id).one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسير غير موجود")
    return (
        db.query(models.HrPayslip)
        .filter(models.HrPayslip.run_id == run_id)
        .order_by(models.HrPayslip.employee_id)
        .all()
    )


@router.get("/payslips/{payslip_id}", response_model=List[schemas.HrPayslipLineOut])
def list_payslip_lines(
    payslip_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_permission_or_role("hr.payslip.view", "admin", "manager")),
):
    slip = (
        db.query(models.HrPayslip)
        .filter(models.HrPayslip.company_id == db.info["company_id"], models.HrPayslip.id == payslip_id)
        .one_or_none()
    )
    if slip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "القسيمة غير موجودة")
    return (
        db.query(models.HrPayslipLine)
        .filter(models.HrPayslipLine.payslip_id == payslip_id)
        .order_by(models.HrPayslipLine.id)
        .all()
    )


# =====================================================================
# السلف والتسوية النهائية وملف WPS (S4)
# =====================================================================

_EOSB_FIRST5_DAYS_PER_YEAR = 21  # 21 يوم راتب لكل سنة من أول 5 سنوات
_EOSB_AFTER5_DAYS_PER_YEAR = 30  # 30 يوم لكل سنة بعد الخامسة


@router.get("/advances", response_model=List[schemas.HrAdvanceOut])
def list_advances(
    employee_id: Optional[int] = None,
    advance_status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.HrAdvance).filter(models.HrAdvance.company_id == db.info["company_id"])
    if employee_id:
        q = q.filter(models.HrAdvance.employee_id == employee_id)
    if advance_status:
        q = q.filter(models.HrAdvance.status == advance_status)
    return q.order_by(models.HrAdvance.id.desc()).all()


@router.post("/payroll/seed-eg-components", response_model=schemas.HrSeedEgComponentsOut)
def seed_eg_salary_components(payload: schemas.HrSeedEgComponentsIn, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """تهيئة خصومات مصرية جاهزة (تأمينات 11% + ضريبة) لموظفين محددين — أو كل الموظفين النشطين.

    المكونات تُبنى لكل موظف إذا لم تكن لديه بالفعل (حسب الاسم). عدّل النسب لاحقًا من بنود الراتب.
    """
    company_id = db.info["company_id"]
    if payload.employee_ids:
        employees = (
            db.query(models.HrEmployee)
            .filter(models.HrEmployee.company_id == company_id, models.HrEmployee.id.in_(payload.employee_ids))
            .all()
        )
    else:
        employees = (
            db.query(models.HrEmployee)
            .filter(models.HrEmployee.company_id == company_id, models.HrEmployee.status == "active")
            .all()
        )
    defaults = [
        {"name": "التأمينات الاجتماعية (حصة الموظف)", "percent": 11.0, "notes": "حصة الموظف الافتراضية 11% من الراتب الأساسي — عدّلها وفق نصيبك المؤمن عليه"},
        {"name": "ضريبة الدخل المصري", "percent": 10.0, "notes": "نسبة مبدئية قابلة للتعديل — الشريحة الفعلية تختلف حسب صافي الدخل السنوي"},
    ]
    created_count = 0
    skipped_count = 0
    for emp in employees:
        for d in defaults:
            exists = db.query(models.HrSalaryComponent).filter(
                models.HrSalaryComponent.company_id == company_id,
                models.HrSalaryComponent.employee_id == emp.id,
                models.HrSalaryComponent.category == "deduction",
                models.HrSalaryComponent.name == d["name"],
            ).first()
            if exists is not None:
                skipped_count += 1
                continue
            db.add(models.HrSalaryComponent(
                company_id=company_id,  # type: ignore
                employee_id=emp.id,  # type: ignore
                category="deduction",  # type: ignore
                name=d["name"],  # type: ignore
                amount_mode="percent_of_base",  # type: ignore
                percent_value=d["percent"],  # type: ignore
                is_active=True,  # type: ignore
                notes=d["notes"],  # type: ignore
                created_by=user.id,
            ))
            created_count += 1
    audit(db, user, "create", "hr_salary_components", None, f"تهيئة خصومات مصرية: {created_count} أُنشئ · {skipped_count} موجود مسبقًا ({len(employees)} موظف)")
    db.commit()
    return schemas.HrSeedEgComponentsOut(created_count=created_count, skipped_count=skipped_count, employees=len(employees))


@router.get("/approval-limits", response_model=schemas.HrApprovalLimitPage)
def list_approval_limits(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """حدود الموافقة على السلف + قائمة المدراء لاختيار من يُضبط له حد."""
    company_id = db.info["company_id"]
    rows = (
        db.query(models.HrAdvanceApprovalLimit, models.User)
        .join(models.User, models.User.id == models.HrAdvanceApprovalLimit.user_id)
        .filter(models.HrAdvanceApprovalLimit.company_id == company_id)
        .order_by(models.User.username)
        .all()
    )
    managers = (
        db.query(models.User)
        .filter(models.User.is_active.is_(True), models.User.role.in_(["admin", "manager"]))
        .order_by(models.User.username)
        .all()
    )
    return schemas.HrApprovalLimitPage(
        limits=[schemas.HrApprovalLimitOut(user_id=u.id, username=u.username, max_amount=float(l.max_amount)) for l, u in rows],
        users=[schemas.HrApprovalLimitUserRow(id=u.id, username=u.username) for u in managers],
    )


@router.put("/approval-limits/{user_id}", response_model=schemas.HrApprovalLimitOut)
def set_approval_limit(user_id: int, payload: schemas.HrApprovalLimitIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """ضبط حد الموافقة على السلف لمستخدم — NULL = إلغاء الحد (غير محدود)."""
    company_id = db.info["company_id"]
    target = db.get(models.User, user_id)
    if target is None or not target.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم غير موجود")
    if payload.max_amount is None:
        db.query(models.HrAdvanceApprovalLimit).filter(
            models.HrAdvanceApprovalLimit.company_id == company_id,
            models.HrAdvanceApprovalLimit.user_id == user_id,
        ).delete(synchronize_session=False)
        db.commit()
        return schemas.HrApprovalLimitOut(user_id=user_id, username=target.username, max_amount=0)
    limit = db.query(models.HrAdvanceApprovalLimit).filter(
        models.HrAdvanceApprovalLimit.company_id == company_id,
        models.HrAdvanceApprovalLimit.user_id == user_id,
    ).first()
    if limit is None:
        limit = models.HrAdvanceApprovalLimit(company_id=company_id, user_id=user_id, max_amount=payload.max_amount)  # type: ignore
        db.add(limit)
    else:
        limit.max_amount = payload.max_amount  # type: ignore
    audit(db, user, "update", "hr_approval_limit", user_id, f"حد سلف المستخدم {target.username}: {payload.max_amount}")
    db.commit()
    return schemas.HrApprovalLimitOut(user_id=user_id, username=target.username, max_amount=float(payload.max_amount))


@router.post("/attendance/import", response_model=schemas.HrAttendanceImportOut)
def import_attendance(payload: schemas.HrAttendanceImportIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """استيراد حضور من ملف جهاز البصمة (لصق CSV): كود الموظف، التاريخ، دخول، خروج.

    upsert لكل موظف/يوم — الموجود يُحدّث والمفقود يُنشأ بمصدر device.
    """
    company_id = db.info["company_id"]
    out = schemas.HrAttendanceImportOut()
    for idx, r in enumerate(payload.rows, start=1):
        try:
            emp = db.query(models.HrEmployee).filter(
                models.HrEmployee.company_id == company_id,
                models.HrEmployee.code == r.employee_code.strip(),
            ).first()
            if emp is None:
                raise ValueError(f"كود موظف غير معروف: {r.employee_code}")
            status_val = r.status or "present"
            existing = db.query(models.HrAttendance).filter(
                models.HrAttendance.company_id == company_id,
                models.HrAttendance.employee_id == emp.id,
                models.HrAttendance.work_date == r.work_date,
            ).first()
            if existing is None:
                db.add(models.HrAttendance(
                    company_id=company_id,
                    employee_id=emp.id,
                    work_date=r.work_date,
                    status=status_val,
                    check_in=r.check_in,
                    check_out=r.check_out,
                    source="device",
                    created_by=user.id,
                ))
                out.created += 1
            else:
                existing.status = status_val
                if r.check_in is not None:
                    existing.check_in = r.check_in
                if r.check_out is not None:
                    existing.check_out = r.check_out
                existing.source = "device"
                out.updated += 1
        except Exception as exc:  # noqa: BLEINE001 — نجمع أخطاء الصفوف بدل إسقاط الدفعة كلها
            out.errors.append(f"سطر {idx}: {exc}")
    audit(db, user, "create", "hr_attendance_import", None, f"استيراد حضور: {out.created} جديد · {out.updated} محدّث · {len(out.errors)} خطأ")
    db.commit()
    return out


# =====================================================================
# إدارة أجهزة البصمة وتكامل ZKTeco / Biometrics
# =====================================================================

@router.get("/biometric-devices", response_model=List[schemas.BiometricDeviceOut])
def list_biometric_devices(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """قائمة أجهزة البصمة المسجلة في الشركة."""
    return db.query(models.BiometricDevice).filter(models.BiometricDevice.company_id == db.info["company_id"]).order_by(models.BiometricDevice.id).all()


@router.post("/biometric-devices", response_model=schemas.BiometricDeviceOut, status_code=status.HTTP_201_CREATED)
def create_biometric_device(payload: schemas.BiometricDeviceCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """تسجيل جهاز بصمة جديد (IP والمنفذ والفرع)."""
    company_id = db.info["company_id"]
    exists = db.query(models.BiometricDevice).filter(
        models.BiometricDevice.company_id == company_id,
        models.BiometricDevice.ip_address == payload.ip_address,
        models.BiometricDevice.port == payload.port,
    ).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"يوجد جهاز مسجل بالفعل بنفس العنوان {payload.ip_address}:{payload.port}")
    dev = models.BiometricDevice(
        company_id=company_id,
        name=payload.name,
        device_model=payload.device_model or "ZKTeco",
        ip_address=payload.ip_address,
        port=payload.port,
        serial_number=payload.serial_number,
        comm_key=payload.comm_key or "0",
        branch_id=payload.branch_id,
        is_active=payload.is_active,
    )
    db.add(dev)
    audit(db, user, "create", "biometric_device", dev, f"جهاز بصمة: {dev.name} ({dev.ip_address})")
    db.commit()
    db.refresh(dev)
    return dev


@router.patch("/biometric-devices/{device_id}", response_model=schemas.BiometricDeviceOut)
def update_biometric_device(device_id: int, payload: schemas.BiometricDeviceUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """تعديل بيانات جهاز بصمة."""
    dev = db.query(models.BiometricDevice).filter(models.BiometricDevice.company_id == db.info["company_id"], models.BiometricDevice.id == device_id).first()
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "جهاز البصمة غير موجود")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(dev, k, v)
    audit(db, user, "update", "biometric_device", dev, f"تعديل جهاز {dev.name}")
    db.commit()
    db.refresh(dev)
    return dev


@router.delete("/biometric-devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_biometric_device(device_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """حذف جهاز بصمة."""
    dev = db.query(models.BiometricDevice).filter(models.BiometricDevice.company_id == db.info["company_id"], models.BiometricDevice.id == device_id).first()
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "جهاز البصمة غير موجود")
    db.delete(dev)
    audit(db, user, "delete", "biometric_device", dev, f"حذف جهاز {dev.name}")
    db.commit()


@router.post("/biometric-devices/{device_id}/ping")
def ping_biometric_device(device_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """فحص جاهزية الاتصال بجهاز البصمة (Ping test / Network check)."""
    dev = db.query(models.BiometricDevice).filter(models.BiometricDevice.company_id == db.info["company_id"], models.BiometricDevice.id == device_id).first()
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "جهاز البصمة غير موجود")
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        res = s.connect_ex((dev.ip_address, dev.port))
        is_online = (res == 0)
    except Exception:
        is_online = False
    finally:
        s.close()
    dev.last_status = "online" if is_online else "offline"
    db.commit()
    return {"device_id": dev.id, "name": dev.name, "ip": dev.ip_address, "port": dev.port, "status": dev.last_status}


@router.post("/biometric-devices/push-punches", response_model=schemas.BiometricSyncSummary)
def push_biometric_punches(payload: schemas.BiometricBatchPush, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """استقبال دفعة حركات بصمة من الجهاز (أو وكيل المزامنة) وتحويلها لسجلات حضور وانصراف مجمعة."""
    company_id = db.info["company_id"]
    from collections import defaultdict

    emp_map = {e.code: e for e in db.query(models.HrEmployee).filter(models.HrEmployee.company_id == company_id).all()}
    unmatched = set()
    created = 0
    updated = 0
    matched = 0

    # تجميع الحركات بحسب (الموظف، تاريخ اليوم)
    punches_by_day = defaultdict(list)
    for p in payload.punches:
        code = p.employee_code.strip()
        if code not in emp_map:
            unmatched.add(code)
            continue
        matched += 1
        w_date = p.timestamp.date()
        hhmm = p.timestamp.strftime("%H:%M")
        punches_by_day[(emp_map[code].id, w_date)].append(hhmm)

    for (emp_id, w_date), times in punches_by_day.items():
        sorted_times = sorted(times)
        cin = sorted_times[0]
        cout = sorted_times[-1] if len(sorted_times) > 1 else None

        existing = db.query(models.HrAttendance).filter(
            models.HrAttendance.company_id == company_id,
            models.HrAttendance.employee_id == emp_id,
            models.HrAttendance.work_date == w_date,
        ).first()

        late, overtime = _attendance_metrics_for(db, company_id, emp_id, "present", cin, cout)

        if existing is None:
            db.add(models.HrAttendance(
                company_id=company_id,
                employee_id=emp_id,
                work_date=w_date,
                status="present",
                check_in=cin,
                check_out=cout,
                late_minutes=late,
                overtime_minutes=overtime,
                source="device",
                created_by=user.id,
            ))
            created += 1
        else:
            if existing.check_in is None or cin < existing.check_in:
                existing.check_in = cin
            if cout and (existing.check_out is None or cout > existing.check_out):
                existing.check_out = cout
            existing.status = "present"
            existing.late_minutes = late
            existing.overtime_minutes = overtime
            existing.source = "device"
            updated += 1

    if payload.device_id:
        dev = db.get(models.BiometricDevice, payload.device_id)
        if dev and dev.company_id == company_id:
            dev.last_sync_at = func.now()
            dev.last_status = "online"

    db.commit()
    return schemas.BiometricSyncSummary(
        device_id=payload.device_id,
        total_received=len(payload.punches),
        matched_punches=matched,
        attendance_records_created=created,
        attendance_records_updated=updated,
        unmatched_employee_codes=list(unmatched),
    )


@router.get("/approval-chains", response_model=schemas.HrApprovalChainPage)
def get_approval_chains(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """مسار الموافقات للإجازات + قائمة المدراء لاختيار الموافقين."""
    company_id = db.info["company_id"]
    levels = (
        db.query(models.HrApprovalChain, models.User)
        .join(models.User, models.User.id == models.HrApprovalChain.approver_user_id, isouter=True)
        .filter(models.HrApprovalChain.company_id == company_id, models.HrApprovalChain.entity_type == "leave")
        .order_by(models.HrApprovalChain.level)
        .all()
    )
    managers = (
        db.query(models.User)
        .filter(models.User.is_active.is_(True), models.User.role.in_(["admin", "manager"]))
        .order_by(models.User.username)
        .all()
    )
    return schemas.HrApprovalChainPage(
        entity_type="leave",
        levels=[
            schemas.HrApprovalChainLevelOut(
                level=c.level, approver_user_id=c.approver_user_id,
                approver_username=u.username if u else None, approver_role=c.approver_role,
            )
            for c, u in levels
        ],
        users=[schemas.HrApprovalLimitUserRow(id=u.id, username=u.username) for u in managers],
    )


@router.put("/approval-chains/leave", response_model=schemas.HrApprovalChainPage)
def set_leave_approval_chain(payload: schemas.HrApprovalChainIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """ضبط مسار موافقات الإجازات: مستويات مرتبة — مسار فارغ يعني موافقة مفردة تقليدية."""
    company_id = db.info["company_id"]
    levels = sorted(payload.levels, key=lambda x: x.level)
    for i, lv in enumerate(levels, start=1):
        if lv.level != i:
            raise HTTPException(422, "المستويات يجب أن تكون متسلسلة من 1")
        if lv.approver_user_id is None and lv.approver_role is None:
            raise HTTPException(422, f"المستوى {lv.level} يحتاج موافقاً (مستخدم أو دور)")
        if lv.approver_user_id is not None:
            target = db.get(models.User, lv.approver_user_id)
            if target is None or not target.is_active:
                raise HTTPException(422, f"الموافق في المستوى {lv.level} غير موجود")
    db.query(models.HrApprovalChain).filter(
        models.HrApprovalChain.company_id == company_id, models.HrApprovalChain.entity_type == "leave"
    ).delete(synchronize_session=False)
    for lv in levels:
        db.add(models.HrApprovalChain(
            company_id=company_id, entity_type="leave", level=lv.level,
            approver_user_id=lv.approver_user_id, approver_role=lv.approver_role,
        ))
    audit(db, user, "update", "hr_approval_chain", None, f"مسار موافقات الإجازات: {len(levels)} مستوى")
    db.commit()
    return get_approval_chains(db=db, _=user)


@router.get("/leave-requests/{request_id}/steps", response_model=List[schemas.HrApprovalStepRow])
def leave_approval_steps(request_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """تاريخ موافقات طلب الإجازة عبر مستويات المسار."""
    rows = (
        db.query(models.HrApprovalStep, models.User)
        .join(models.User, models.User.id == models.HrApprovalStep.approver_user_id, isouter=True)
        .filter(
            models.HrApprovalStep.company_id == db.info["company_id"],
            models.HrApprovalStep.entity_type == "leave",
            models.HrApprovalStep.entity_id == request_id,
        )
        .order_by(models.HrApprovalStep.level)
        .all()
    )
    return [
        schemas.HrApprovalStepRow(
            level=s.level, approver_username=u.username if u else None,
            decision=s.decision, notes=s.notes,
            created_at=s.created_at.isoformat() if s.created_at else None,
        )
        for s, u in rows
    ]


@router.get("/payroll-runs/{run_id}/form-6h.xlsx")
def download_form_6h(run_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """نموذج 6ح — التأمينات الاجتماعية: أعمدة رسمية لكل مؤمن عليه من قسائم المسير."""
    from ..exports import XLSX_MIME, build_tables_xlsx

    company_id = db.info["company_id"]
    run = db.get(models.HrPayrollRun, run_id)
    if run is None or run.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسير غير موجود")
    slips = (
        db.query(models.HrPayslip, models.HrEmployee)
        .join(models.HrEmployee, models.HrEmployee.id == models.HrPayslip.employee_id)
        .filter(models.HrPayslip.run_id == run_id)
        .order_by(models.HrEmployee.code)
        .all()
    )
    EMP_RATE, CO_RATE = 11.0, 18.75  # حصة الموظف / حصة الشركة من الأجر الخاضع
    rows = []
    total_emp = total_co = 0.0
    for slip, emp in slips:
        insurable = float(slip.base_salary or 0)
        emp_share = round(insurable * EMP_RATE / 100, 2)
        co_share = round(insurable * CO_RATE / 100, 2)
        total_emp += emp_share
        total_co += co_share
        rows.append([
            ("text", emp.code), ("text", emp.full_name), ("text", emp.national_id or ""),
            ("text", emp.insurance_number or ""), ("money", insurable),
            ("money", emp_share), ("money", co_share), ("money", round(emp_share + co_share, 2)),
        ])
    content = build_tables_xlsx(
        "نموذج 6ح — التأمينات الاجتماعية",
        f"مسير {run.year}-{int(run.month):02d} · حصة الموظف {EMP_RATE}% · حصة الشركة {CO_RATE}%",
        [("المؤمن عليهم", ["الكود", "الاسم", "الرقم القومي", "رقم التأمين", "الأجر الخاضع", "حصة الموظف", "حصة الشركة", "الإجمالي"], rows)],
    )
    return Response(content, media_type=XLSX_MIME, headers={"Content-Disposition": f"attachment; filename=form6h-{run.year}-{int(run.month):02d}.xlsx"})


@router.get("/payroll-runs/{run_id}/form-4.xlsx")
def download_form_4(run_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """إقرار ضريبة كسب العمل: إجمالي المستحقات والخصومات والضريبة لكل موظف من قسائم المسير."""
    from ..exports import XLSX_MIME, build_tables_xlsx

    company_id = db.info["company_id"]
    run = db.get(models.HrPayrollRun, run_id)
    if run is None or run.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسير غير موجود")
    slips = (
        db.query(models.HrPayslip, models.HrEmployee)
        .join(models.HrEmployee, models.HrEmployee.id == models.HrPayslip.employee_id)
        .filter(models.HrPayslip.run_id == run_id)
        .order_by(models.HrEmployee.code)
        .all()
    )
    slip_ids = [s.id for s, _e in slips]
    tax_by_slip: dict = {}
    if slip_ids:
        lines = db.query(models.HrPayslipLine).filter(models.HrPayslipLine.payslip_id.in_(slip_ids)).all()
        for line in lines:
            if line.category == "deduction" and "ضريبة" in (line.name or ""):
                tax_by_slip[line.payslip_id] = tax_by_slip.get(line.payslip_id, 0.0) + float(line.amount or 0)
    rows = []
    total_tax = 0.0
    for slip, emp in slips:
        tax = tax_by_slip.get(slip.id, 0.0)
        total_tax += tax
        rows.append([
            ("text", emp.code), ("text", emp.full_name), ("text", emp.national_id or ""),
            ("money", float(slip.base_salary or 0)), ("money", float(slip.total_earnings or 0)),
            ("money", float(slip.total_deductions or 0)), ("money", tax), ("money", float(slip.net_pay or 0)),
        ])
    content = build_tables_xlsx(
        "إقرار ضريبة كسب العمل (نموذج 4)",
        f"مسير {run.year}-{int(run.month):02d} · إجمالي الضريبة المقطوعة: {total_tax:.2f} ج.م",
        [("الموظفون", ["الكود", "الاسم", "الرقم القومي", "الأساسي", "إجمالي المستحقات", "إجمالي الخصومات", "الضريبة المقطوعة", "الصافي"], rows)],
    )
    return Response(content, media_type=XLSX_MIME, headers={"Content-Disposition": f"attachment; filename=form4-{run.year}-{int(run.month):02d}.xlsx"})


@router.post("/advances", response_model=schemas.HrAdvanceOut, status_code=status.HTTP_201_CREATED)
def create_advance(payload: schemas.HrAdvanceCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    emp = _employee_or_404(db, payload.employee_id)
    # حد الموافقة على السلف: ما يتجاوز حد المُنشئ يُرفض (مدير المنصة ودور admin يتجاوزان)
    if not user.is_platform_admin and user_role(user) != "admin":
        limit = db.query(models.HrAdvanceApprovalLimit).filter(
            models.HrAdvanceApprovalLimit.company_id == company_id,
            models.HrAdvanceApprovalLimit.user_id == user.id,
        ).first()
        if limit is not None and Decimal(str(payload.amount)) > Decimal(str(limit.max_amount)):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"قيمة السلفة {payload.amount} تتجاوز حد الموافقة المسموح لك به ({limit.max_amount})",
            )
    row = models.HrAdvance(
        company_id=company_id,
        employee_id=emp.id,
        amount=payload.amount,
        installments_count=payload.installments_count,
        start_year=payload.start_year,
        start_month=payload.start_month,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "create", "hr_advance", row, f"{emp.code} · {row.amount} على {row.installments_count} قسطاً · من {row.start_year}-{int(row.start_month):02d}")
    return row


@router.patch("/advances/{advance_id}", response_model=schemas.HrAdvanceOut)
def update_advance(advance_id: int, payload: schemas.HrAdvanceUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """تغيير حالة السلفة فقط (تثبيت/إلغاء) — القيمة والأقساط مقفلَتان لحماية النفاذية المالية."""
    row = db.query(models.HrAdvance).filter(models.HrAdvance.company_id == db.info["company_id"], models.HrAdvance.id == advance_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "السلفة غير موجودة")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data:
        row.status = data["status"]
    if data.get("notes") is not None:
        row.notes = data["notes"]
    audit(db, user, "update", "hr_advance", row, f"{row.advance_code} · الحالة: {row.status}")  # type: ignore[union-attr]
    db.commit()
    db.refresh(row)
    return row


@router.delete("/advances/{advance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_advance(advance_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """حذف سلفة لم تُخصم لها أقساط في أي مسير بعد."""
    row = db.query(models.HrAdvance).filter(models.HrAdvance.company_id == db.info["company_id"], models.HrAdvance.id == advance_id).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "السلفة غير موجودة")
    used = db.query(models.HrPayslipLine).filter(models.HrPayslipLine.advance_id == row.id).first()
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, "لا يمكن الحذف: قُسِّط منها في مسير — ألغِها مع منظومة القيود بدل الحذف")
    audit(db, user, "delete", "hr_advance", row.id, row.advance_code)  # type: ignore[union-attr]
    db.delete(row)
    db.commit()


def _eosb_days_and_service(hire_date: date, term_date: date) -> tuple[int, Decimal, Decimal]:
    """(أيام الخدمة، سنوات الخدمة، أيام EOSB): 21 يوم/سنة لأول 5 سنوات ثم 30، تناسب جزئي بالأيام/365.25."""
    if term_date < hire_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "تاريخ الإنهاء قبل تاريخ التعيين")
    service_days = (term_date - hire_date).days + 1
    years = Decimal(service_days) / Decimal("365.25")
    first = min(years, Decimal("5"))
    after = max(Decimal("0"), years - Decimal("5"))
    eosb_days = (first * _EOSB_FIRST5_DAYS_PER_YEAR + after * _EOSB_AFTER5_DAYS_PER_YEAR).quantize(Decimal("0.1"))
    return service_days, years.quantize(Decimal("0.01")), eosb_days


@router.post("/employees/{employee_id}/settlement", response_model=schemas.HrSettlementOut, status_code=status.HTTP_201_CREATED)
def create_settlement(employee_id: int, payload: schemas.HrSettlementCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """تسوية نهائية عند إنهاء الخدمة (سجل واحد لكل موظف): EOSB + إجازات غير مستخدمة − سلف متبقية."""
    company_id = db.info["company_id"]
    emp = db.get(models.HrEmployee, employee_id)
    if emp is None or emp.company_id != company_id:  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الموظف غير موجود")
    if emp.status != "terminated" or not emp.terminated_at:  # type: ignore[operator]
        raise HTTPException(status.HTTP_409_CONFLICT, "التسوية النهائية تكون بعد إنهاء خدمة الموظف فقط")
    existing = db.query(models.HrSettlement).filter(models.HrSettlement.company_id == company_id, models.HrSettlement.employee_id == emp.id).one_or_none()  # type: ignore[arg-type]
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "توجد تسوية نهائية لهذا الموظف مسبقاً")

    base_salary = _employee_base_salary(emp)
    if base_salary <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "الموظف بلا راتب معروف — عنوان التسوية محتاج للأساس")
    service_days, service_years, eosb_days = _eosb_days_and_service(emp.hire_date, emp.terminated_at)  # type: ignore[arg-type]
    eosb_amount = (base_salary / Decimal("30") * eosb_days).quantize(Decimal("0.01"))

    # رصيد الإجازات المدفوعة غير المستخدمة (كل السنوات)
    unused_leave_days = Decimal("0")
    paid_balances = (
        db.query(models.HrLeaveBalance)
        .join(models.HrLeaveType, models.HrLeaveBalance.leave_type_id == models.HrLeaveType.id)
        .filter(
            models.HrLeaveBalance.company_id == company_id,
            models.HrLeaveBalance.employee_id == emp.id,
            models.HrLeaveType.is_paid.is_(True),
        )
        .all()
    )
    for b in paid_balances:
        unused_leave_days += b.remaining_days
    unused_leave_amount = (base_salary / Decimal("30") * unused_leave_days).quantize(Decimal("0.01"))

    # المتبقي من السلف النشطة
    advances_remaining = Decimal("0")
    for adv in (
        db.query(models.HrAdvance)
        .filter(models.HrAdvance.company_id == company_id, models.HrAdvance.employee_id == emp.id, models.HrAdvance.status == "active")
        .all()
    ):
        consumed = (
            db.query(func.coalesce(func.sum(models.HrPayslipLine.amount), 0))
            .filter(models.HrPayslipLine.advance_id == adv.id)
            .scalar()
        )
        advances_remaining += max(Decimal("0"), Decimal(adv.amount) - Decimal(consumed))

    total_due = (eosb_amount + unused_leave_amount - advances_remaining).quantize(Decimal("0.01"))
    row = models.HrSettlement(
        company_id=company_id,
        employee_id=emp.id,
        termination_date=emp.terminated_at,
        service_days=service_days,
        service_years=service_years,
        eosb_days=eosb_days,
        eosb_amount=eosb_amount,
        unused_leave_days=unused_leave_days,
        unused_leave_amount=unused_leave_amount,
        advances_remaining=advances_remaining,
        total_due=total_due,
        note=payload.note,
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_settlement", row, f"{emp.code} · EOSB {eosb_days} يوم = {eosb_amount} · صافي الاستحقاق {total_due}")  # type: ignore[union-attr]
    db.commit()
    db.refresh(row)
    return row


@router.get("/settlements", response_model=List[schemas.HrSettlementOut])
def list_settlements(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return (
        db.query(models.HrSettlement)
        .filter(models.HrSettlement.company_id == db.info["company_id"])
        .order_by(models.HrSettlement.id.desc())
        .all()
    )


@router.get("/payroll-runs/{run_id}/wps.csv")
def download_wps(run_id: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """ملف WPS (حماية الأجور) بصيغة CSV: رقم الموظف، الاسم، الهوية، IBAN، الصافي — مسيرات مُرحّلة فقط."""
    run = db.query(models.HrPayrollRun).filter(models.HrPayrollRun.company_id == db.info["company_id"], models.HrPayrollRun.id == run_id).one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسير غير موجود")
    if run.status != "posted":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, "ملف WPS يتطلب مسيراً مُرحّلاً (قسائم نهائية)")

    company = db.get(models.Company, db.info["company_id"])
    slips = (
        db.query(models.HrPayslip)
        .filter(models.HrPayslip.run_id == run_id)
        .all()
    )
    employees = {e.id: e for e in db.query(models.HrEmployee).filter(models.HrEmployee.company_id == db.info["company_id"]).all()}

    import csv as _csv
    import io as _io

    buf = _io.StringIO()
    writer = _csv.writer(buf, quoting=_csv.QUOTE_MINIMAL)
    writer.writerow(["WPS", f"{run.year}-{int(run.month):02d}", company.name if company else ""])  # type: ignore[union-attr]
    writer.writerow(["EMP_CODE", "EMP_NAME", "NATIONAL_ID", "BANK_IBAN", "NET_AMOUNT"])
    for slip in sorted(slips, key=lambda s: employees.get(s.employee_id).code if employees.get(s.employee_id) else ""):
        emp = employees.get(slip.employee_id)
        if emp is None:
            continue
        writer.writerow([
            emp.code,
            emp.full_name,
            emp.national_id or "",
            (emp.bank_account or "").replace(" ", ""),
            f"{slip.net_pay:.2f}",
        ])
    total = sum(Decimal(s.net_pay) for s in slips)
    writer.writerow(["TOTAL", "", "", "", f"{total:.2f}"])

    content = _io.BytesIO(buf.getvalue().encode("utf-8-sig"))  # BOM لفتح عربي سايم في Excel
    filename = f"wps-{run.year}-{int(run.month):02d}.csv"
    return Response(
        content=content.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =====================================================================
# الخدمة الذاتية للموظف (S5): نظرة ملف + أرصدة إجازات + حضور + قسائم + طلبات
# لموظف مرتبط بحساب دخوله — بلا وصول لبيانات موظفين آخرين.
# =====================================================================

@router.get("/me", response_model=schemas.HrMeEmployeeOut)
def me_profile(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    emp = _employee_for_user(db, user)
    return emp


@router.get("/me/leave-balances", response_model=List[schemas.HrLeaveBalanceOut])
def me_leave_balances(year: Optional[int] = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    emp = _employee_for_user(db, user)
    balance_year = year or date.today().year
    leave_types = (
        db.query(models.HrLeaveType)
        .filter(models.HrLeaveType.company_id == db.info["company_id"], models.HrLeaveType.is_active.is_(True))
        .all()
    )
    for lt_model in leave_types:
        _ensure_leave_balance(db, db.info["company_id"], emp, lt_model, balance_year)
    db.commit()
    return (
        db.query(models.HrLeaveBalance)
        .filter(
            models.HrLeaveBalance.company_id == db.info["company_id"],
            models.HrLeaveBalance.employee_id == emp.id,
            models.HrLeaveBalance.year == balance_year,
        )
        .all()
    )


@router.get("/me/attendance", response_model=List[schemas.HrAttendanceOut])
def me_attendance(
    response: Response,
    year: Optional[int] = None,
    month: Optional[int] = None,
    skip: int = 0,
    limit: int = 60,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    emp = _employee_for_user(db, user)
    q = db.query(models.HrAttendance).filter(
        models.HrAttendance.company_id == db.info["company_id"],
        models.HrAttendance.employee_id == emp.id,
    )
    if year:
        q = q.filter(func.extract("year", models.HrAttendance.work_date) == year)
    if month:
        q = q.filter(func.extract("month", models.HrAttendance.work_date) == month)
    return paginate(q, response, skip, limit, models.HrAttendance.work_date.desc(), models.HrAttendance.id.desc())


@router.get("/me/leave-requests", response_model=List[schemas.HrLeaveRequestOut])
def me_leave_requests(
    response: Response,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    emp = _employee_for_user(db, user)
    q = db.query(models.HrLeaveRequest).filter(
        models.HrLeaveRequest.company_id == db.info["company_id"],
        models.HrLeaveRequest.employee_id == emp.id,
    )
    return paginate(q, response, skip, limit, models.HrLeaveRequest.id.desc())


@router.post("/me/leave-requests", response_model=schemas.HrLeaveRequestOut, status_code=status.HTTP_201_CREATED)
def me_create_leave_request(payload: schemas.HrMeLeaveRequestCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """الموظف يطلب إجازة لنفسه — تدخل منظومة الموافقات المديرية نفسها (pending)."""
    emp = _employee_for_user(db, user)
    company_id = db.info["company_id"]
    lt_model = db.get(models.HrLeaveType, payload.leave_type_id)
    if lt_model is None or lt_model.company_id != company_id or not lt_model.is_active:  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نوع الإجازة غير موجود أو غير مفعّل في هذه الشركة")
    if payload.to_date < payload.from_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "تاريخ النهاية يجب أن يكون بعد تاريخ البداية")
    if payload.from_date < emp.hire_date:  # type: ignore[operator]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لا يمكن طلب إجازة قبل تاريخ مباشرة العمل")
    _check_leave_overlap(db, company_id, emp.id, payload.from_date, payload.to_date)
    row = models.HrLeaveRequest(
        company_id=company_id,
        employee_id=emp.id,
        leave_type_id=payload.leave_type_id,
        from_date=payload.from_date,
        to_date=payload.to_date,
        days=_leave_days(payload.from_date, payload.to_date),
        reason=payload.reason,
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_leave_request", row, f"طلب ذاتي · {emp.code} · {lt_model.name} · {row.days} يوم")
    db.commit()
    db.refresh(row)
    return row


@router.get("/me/payslips", response_model=List[schemas.HrMePayslipOut])
def me_payslips(
    response: Response,
    skip: int = 0,
    limit: int = 24,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    emp = _employee_for_user(db, user)
    q = (
        db.query(models.HrPayslip, models.HrPayrollRun)
        .join(models.HrPayrollRun, models.HrPayslip.run_id == models.HrPayrollRun.id)
        .filter(models.HrPayslip.company_id == db.info["company_id"], models.HrPayslip.employee_id == emp.id)
    )
    rows = paginate(
        q, response, skip, limit,
        models.HrPayrollRun.year.desc(), models.HrPayrollRun.month.desc(), models.HrPayrollRun.id.desc(),
    )
    out: List[schemas.HrMePayslipOut] = []
    for slip, run in rows:  # rows = قائمة أزواج عند دالة paginate
        out.append(schemas.HrMePayslipOut(
            id=slip.id,
            run_id=run.id,
            year=run.year,
            month=run.month,
            run_status=run.status,
            base_salary=slip.base_salary,
            total_earnings=slip.total_earnings,
            total_deductions=slip.total_deductions,
            net_pay=slip.net_pay,
        ))
    return out


@router.get("/me/attendance-corrections", response_model=List[schemas.HrAttendanceCorrectionOut])
def me_attendance_corrections(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    emp = _employee_for_user(db, user)
    return (
        db.query(models.HrAttendanceCorrection)
        .filter(models.HrAttendanceCorrection.company_id == db.info["company_id"], models.HrAttendanceCorrection.employee_id == emp.id)
        .order_by(models.HrAttendanceCorrection.work_date.desc(), models.HrAttendanceCorrection.id.desc())
        .all()
    )


@router.post("/me/attendance-corrections", response_model=schemas.HrAttendanceCorrectionOut, status_code=status.HTTP_201_CREATED)
def me_create_attendance_correction(payload: schemas.HrAttendanceCorrectionCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    emp = _employee_for_user(db, user)
    company_id = db.info["company_id"]
    if payload.work_date > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لا يمكن طلب تصحيح ليوم مستقبلي")
    if not payload.requested_check_in and not payload.requested_check_out:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "أدخل وقت دخول أو وقت خروج للتصحيح")
    if (
        payload.requested_check_in and payload.requested_check_out
        and payload.requested_check_out < payload.requested_check_in
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "وقت الخروج يجب أن يكون بعد الدخول")
    existing = (
        db.query(models.HrAttendanceCorrection)
        .filter(
            models.HrAttendanceCorrection.company_id == company_id,
            models.HrAttendanceCorrection.employee_id == emp.id,
            models.HrAttendanceCorrection.work_date == payload.work_date,
        )
        .one_or_none()
    )
    if existing:
        if existing.status == "pending":
            raise HTTPException(status.HTTP_409_CONFLICT, "لديك طلب تصحيح معلّق لنفس اليوم")
        raise HTTPException(status.HTTP_409_CONFLICT, "اعتُمِد/رُفِض طلب لتصحيح هذا اليوم — اطلب تصحيح بيانات الحضور من إدارة HR")
    row = models.HrAttendanceCorrection(
        company_id=company_id,
        employee_id=emp.id,
        work_date=payload.work_date,
        requested_check_in=payload.requested_check_in,
        requested_check_out=payload.requested_check_out,
        reason=payload.reason.strip(),
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_attendance_correction", row, f"طلب ذاتي · {emp.code} · {row.work_date}")
    db.commit()
    db.refresh(row)
    return row


# ------------------------------------------------------------------ إدارة مطالبات التصحيح (للمدير)

def _correction_or_404(db: Session, correction_id: int) -> models.HrAttendanceCorrection:
    row = (
        db.query(models.HrAttendanceCorrection)
        .filter(models.HrAttendanceCorrection.company_id == db.info["company_id"], models.HrAttendanceCorrection.id == correction_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "طلب التصحيح غير موجود")
    return row


@router.get("/attendance-corrections", response_model=List[schemas.HrAttendanceCorrectionOut])
def list_attendance_corrections(
    response: Response,
    correction_status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    q = db.query(models.HrAttendanceCorrection).filter(models.HrAttendanceCorrection.company_id == db.info["company_id"])
    if correction_status:
        q = q.filter(models.HrAttendanceCorrection.status == correction_status)
    return paginate(q, response, skip, limit, models.HrAttendanceCorrection.id.desc())


@router.post("/attendance-corrections/{correction_id}/approve", response_model=schemas.HrAttendanceCorrectionOut)
def approve_attendance_correction(correction_id: int, payload: schemas.HrCorrectionDecision, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _correction_or_404(db, correction_id)
    if row.status != "pending":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, f"لا يمكن الموافقة: حالة الطلب «{row.status}»")  # type: ignore[union-attr]
    # تطبيق التصحيح: تعديل سجل الحضور إن وجد وإلا إنشاؤه (الحالة حاضرة)
    company_id = db.info["company_id"]
    slip = (
        db.query(models.HrAttendance)
        .filter(
            models.HrAttendance.company_id == company_id,
            models.HrAttendance.employee_id == row.employee_id,
            models.HrAttendance.work_date == row.work_date,
        )
        .one_or_none()
    )
    created = False
    if slip is None:
        slip = models.HrAttendance(
            company_id=company_id,
            employee_id=row.employee_id,
            work_date=row.work_date,
            status="present",
            check_in=row.requested_check_in,
            check_out=row.requested_check_out,
            source="manual",
            created_by=user.id,
        )
        db.add(slip)
        db.flush()
        created = True
    else:
        if row.requested_check_in:  # type: ignore[union-attr]
            slip.check_in = row.requested_check_in  # type: ignore[assignment]
        if row.requested_check_out:  # type: ignore[union-attr]
            slip.check_out = row.requested_check_out  # type: ignore[assignment]
    if slip.status in ("absent", "excused") and slip.check_in:
        slip.status = "present"
    late, overtime = _attendance_metrics_for(db, company_id, row.employee_id, slip.status, slip.check_in, slip.check_out)  # type: ignore[arg-type]
    slip.late_minutes = late  # type: ignore[assignment]
    slip.overtime_minutes = overtime  # type: ignore[assignment]
    row.status = "approved"  # type: ignore[assignment]
    row.decision_note = payload.decision_note  # type: ignore[assignment]
    row.decided_by = user.id
    row.decided_at = func.now()
    row.applied_attendance_id = slip.id  # type: ignore
    audit(db, user, "approve", "hr_attendance_correction", row, f"موافقة تصحيح · {row.employee_code} · {row.work_date}")  # type: ignore[arg-type]
    db.commit()
    db.refresh(row)
    return row


@router.post("/attendance-corrections/{correction_id}/reject", response_model=schemas.HrAttendanceCorrectionOut)
def reject_attendance_correction(correction_id: int, payload: schemas.HrCorrectionDecision, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _correction_or_404(db, correction_id)
    if row.status != "pending":  # type: ignore[union-attr]
        raise HTTPException(status.HTTP_409_CONFLICT, f"لا يمكن الرفض: حالة الطلب «{row.status}»")  # type: ignore[union-attr]
    row.status = "rejected"  # type: ignore[assignment]
    row.decision_note = payload.decision_note  # type: ignore[assignment]
    row.decided_by = user.id
    row.decided_at = func.now()
    audit(db, user, "reject", "hr_attendance_correction", row, "رفض تصحيح")  # type: ignore[arg-type]
    db.commit()
    db.refresh(row)
    return row


# =====================================================================
# S6 — التوظيف (ATS): إعلانات + متقدمون + تحويل للتوظيف
# =====================================================================

_STAGE_ORDER = ["applied", "screening", "interview", "offer"]


def _posting_or_404(db: Session, posting_id: int) -> models.HrJobPosting:
    row = (
        db.query(models.HrJobPosting)
        .filter(models.HrJobPosting.company_id == db.info["company_id"], models.HrJobPosting.id == posting_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "إعلان التوظيف غير موجود")
    return row


def _applicant_or_404(db: Session, applicant_id: int) -> models.HrJobApplicant:
    row = (
        db.query(models.HrJobApplicant)
        .filter(models.HrJobApplicant.company_id == db.info["company_id"], models.HrJobApplicant.id == applicant_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المتقدم غير موجود")
    return row


@router.post("/job-postings", response_model=schemas.HrJobPostingOut, status_code=status.HTTP_201_CREATED)
def create_job_posting(payload: schemas.HrJobPostingCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    company_id = db.info["company_id"]
    row = models.HrJobPosting(
        company_id=company_id,
        code=unique_code(db, models.HrJobPosting, company_id, payload.title, "JOB"),
        title=payload.title.strip(),
        department_id=_validate_fk(db, company_id, payload.department_id, models.Department, "الإدارة"),
        branch_id=_validate_fk(db, company_id, payload.branch_id, models.Branch, "الفرع"),
        openings=payload.openings,
        employment_type=payload.employment_type,
        description=payload.description,
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_job_posting", row, f"إعلان توظيف {row.title} · {row.openings} منصب")
    db.commit()
    db.refresh(row)
    return row


@router.get("/job-postings", response_model=List[schemas.HrJobPostingOut])
def list_job_postings(
    response: Response,
    posting_status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    q = db.query(models.HrJobPosting).filter(models.HrJobPosting.company_id == db.info["company_id"])
    if posting_status:
        q = q.filter(models.HrJobPosting.status == posting_status)
    return paginate(q, response, skip, limit, models.HrJobPosting.id.desc())


@router.patch("/job-postings/{posting_id}", response_model=schemas.HrJobPostingOut)
def update_job_posting(posting_id: int, payload: schemas.HrJobPostingUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _posting_or_404(db, posting_id)
    data = payload.model_dump(exclude_unset=True)
    if "department_id" in data:
        data["department_id"] = _validate_fk(db, db.info["company_id"], data["department_id"], models.Department, "الإدارة")
    if "branch_id" in data:
        data["branch_id"] = _validate_fk(db, db.info["company_id"], data["branch_id"], models.Branch, "الفرع")
    if "status" in data and data["status"] != row.status:
        if row.status == "filled" and data["status"] != "closed":
            raise HTTPException(status.HTTP_409_CONFLICT, "إعلان اكتمل (filled) — يمكن إغلاقه فقط")
        if data["status"] in ("closed", "filled") and row.closed_at is None:
            row.closed_at = func.now()
        elif data["status"] in ("open", "on_hold"):
            row.closed_at = None
    for field, value in data.items():
        setattr(row, field, value)
    audit(db, user, "update", "hr_job_posting", row, f"تعديل إعلان {row.code} · الحالة {row.status} · المناصب {row.openings}")
    db.commit()
    db.refresh(row)
    return row


@router.post("/job-postings/{posting_id}/applicants", response_model=schemas.HrApplicantOut, status_code=status.HTTP_201_CREATED)
def create_applicant(posting_id: int, payload: schemas.HrApplicantCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    posting = _posting_or_404(db, posting_id)
    if posting.status not in ("open", "on_hold"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"الإعلان «{posting.status}» — لا يقبل متقدمين جدداً")
    dup = (
        db.query(models.HrJobApplicant)
        .filter(
            models.HrJobApplicant.company_id == db.info["company_id"],
            models.HrJobApplicant.posting_id == posting_id,
            func.lower(models.HrJobApplicant.email) == payload.email.strip().lower(),
        )
        .first()
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "نفس البريد الإلكتروني متقدم لهذه الوظيفة بالفعل")
    row = models.HrJobApplicant(
        company_id=db.info["company_id"],
        posting_id=posting_id,
        full_name=payload.full_name.strip(),
        email=payload.email.strip(),
        phone=payload.phone,
        source=payload.source,
        resume_text=payload.resume_text,
        rating=payload.rating,
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_job_applicant", row, f"متقدم {row.full_name} على {posting.code}")
    db.commit()
    db.refresh(row)
    return row


@router.get("/applicants", response_model=List[schemas.HrApplicantOut])
def list_applicants(
    response: Response,
    posting_id: Optional[int] = None,
    stage: Optional[schemas.ApplicantStage] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    q = db.query(models.HrJobApplicant).filter(models.HrJobApplicant.company_id == db.info["company_id"])
    if posting_id:
        q = q.filter(models.HrJobApplicant.posting_id == posting_id)
    if stage:
        q = q.filter(models.HrJobApplicant.stage == stage)
    return paginate(q, response, skip, limit, models.HrJobApplicant.id.desc())


@router.patch("/applicants/{applicant_id}", response_model=schemas.HrApplicantOut)
def update_applicant(applicant_id: int, payload: schemas.HrApplicantUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _applicant_or_404(db, applicant_id)
    data = payload.model_dump(exclude_unset=True)
    if "email" in data:
        dup = (
            db.query(models.HrJobApplicant)
            .filter(
                models.HrJobApplicant.company_id == db.info["company_id"],
                models.HrJobApplicant.posting_id == row.posting_id,
                func.lower(models.HrJobApplicant.email) == str(data["email"]).strip().lower(),
                models.HrJobApplicant.id != applicant_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "نفس البريد متقدم لهذه الوظيفة بالفعل")
    for field, value in data.items():
        setattr(row, field, value)
    audit(db, user, "update", "hr_job_applicant", row, f"تعديل بيانات متقدم {row.full_name}")
    db.commit()
    db.refresh(row)
    return row


@router.post("/applicants/{applicant_id}/advance", response_model=schemas.HrApplicantOut)
def advance_applicant(applicant_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """ترقية مرحلية: applied → screening → interview → offer (hired حصراً عبر hire، rejected عبر reject)."""
    row = _applicant_or_404(db, applicant_id)
    if row.stage == "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, "المتقدم مرفوض — لا يمكن دُركه مجدداً")
    if row.stage not in _STAGE_ORDER:
        raise HTTPException(status.HTTP_409_CONFLICT, f"المرحلة «{row.stage}» نهائية")
    posting = _posting_or_404(db, row.posting_id)  # type: ignore[arg-type]
    if posting.status not in ("open", "on_hold"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"الإعلان «{posting.status}» — لا تُدار مراحله")
    target = _STAGE_ORDER[_STAGE_ORDER.index(row.stage) + 1]  # type: ignore[arg-type]
    row.stage = target  # type: ignore[assignment]
    audit(db, user, "update", "hr_job_applicant", row, f"تدرّج {row.full_name} إلى المرحلة «{target}»")
    db.commit()
    db.refresh(row)
    return row


@router.post("/applicants/{applicant_id}/reject", response_model=schemas.HrApplicantOut)
def reject_applicant(applicant_id: int, payload: schemas.HrCorrectionDecision, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _applicant_or_404(db, applicant_id)
    if row.stage in ("hired", "rejected"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"المرحلة «{row.stage}» نهائية")
    row.stage = "rejected"  # type: ignore[assignment]
    row.note = payload.decision_note  # type: ignore[assignment]
    row.decided_at = func.now()
    audit(db, user, "reject", "hr_job_applicant", row, f"رفض متقدم {row.full_name}")
    db.commit()
    db.refresh(row)
    return row


@router.post("/applicants/{applicant_id}/hire", response_model=schemas.HrApplicantOut)
def hire_applicant(applicant_id: int, payload: schemas.HrApplicantHire, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    """تحويل المتقدم (المرحلة offer) إلى ملف موظف كامل + إغلاق معلق الإعلان."""
    row = _applicant_or_404(db, applicant_id)
    if row.stage == "hired":
        raise HTTPException(status.HTTP_409_CONFLICT, "المتقدم تم تعيينه بالفعل")
    if row.stage != "offer":
        raise HTTPException(status.HTTP_409_CONFLICT, "التعيين متاح للمتقدم في مرحلة عرض العمل (offer) فقط")
    posting = _posting_or_404(db, row.posting_id)  # type: ignore[arg-type]
    if posting.status not in ("open", "on_hold"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"الإعلان «{posting.status}» — لا يقبل تعيينات")
    if posting.hired_count >= posting.openings:
        raise HTTPException(status.HTTP_409_CONFLICT, "اكتملت مناصب الإعلان — غيّر عدد المناصب أو أغلق الإعلان")

    existing_name = (
        db.query(models.HrEmployee)
        .filter(models.HrEmployee.company_id == db.info["company_id"], models.HrEmployee.full_name == row.full_name)
        .first()
    )
    if existing_name:
        raise HTTPException(status.HTTP_409_CONFLICT, "يوجد موظف بنفس الاسم بالفعل")
    emp = models.HrEmployee(
        company_id=db.info["company_id"],
        code=unique_code(db, models.HrEmployee, db.info["company_id"], row.full_name, "EMP"),
        full_name=row.full_name,
        email=row.email,
        phone=row.phone,
        department_id=posting.department_id,
        branch_id=posting.branch_id,
        hire_date=payload.hire_date or date.today(),
        basic_salary=payload.basic_salary,
        status="probation",
        notes=f"تعيين من التوظيف {posting.code} · المصدر: {row.source or 'غير محدد'}",
    )
    db.add(emp)
    db.flush()
    row.stage = "hired"  # type: ignore[assignment]
    row.hired_employee_id = emp.id  # type: ignore[assignment]
    row.decided_at = func.now()
    posting.hired_count = posting.hired_count + 1  # type: ignore[assignment]
    if posting.hired_count >= posting.openings:  # type: ignore[operator]
        posting.status = "filled"  # type: ignore[assignment]
        posting.closed_at = func.now()
    audit(db, user, "hire", "hr_job_applicant", row, f"تعيين {row.full_name} — employee #{emp.id}")
    db.commit()
    db.refresh(row)
    return row


# =====================================================================
# S6 — الأداء: دورات تقييم + تقييمات
# =====================================================================

def _cycle_or_404(db: Session, cycle_id: int) -> models.HrReviewCycle:
    row = (
        db.query(models.HrReviewCycle)
        .filter(models.HrReviewCycle.company_id == db.info["company_id"], models.HrReviewCycle.id == cycle_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "دورة التقييم غير موجودة")
    return row


@router.post("/review-cycles", response_model=schemas.HrReviewCycleOut, status_code=status.HTTP_201_CREATED)
def create_review_cycle(payload: schemas.HrReviewCycleCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    if payload.period_end < payload.period_start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نهاية الفترة يجب أن تكون بعد بدايتها")
    row = models.HrReviewCycle(
        company_id=db.info["company_id"],
        name=payload.name.strip(),
        period_start=payload.period_start,
        period_end=payload.period_end,
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_review_cycle", row, f"دورة تقييم {row.name}")
    db.commit()
    db.refresh(row)
    return row


@router.get("/review-cycles", response_model=List[schemas.HrReviewCycleOut])
def list_review_cycles(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    return (
        db.query(models.HrReviewCycle)
        .filter(models.HrReviewCycle.company_id == db.info["company_id"])
        .order_by(models.HrReviewCycle.id.desc())
        .all()
    )


@router.post("/review-cycles/{cycle_id}/close", response_model=schemas.HrReviewCycleOut)
def close_review_cycle(cycle_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _cycle_or_404(db, cycle_id)
    if row.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "الدورة مغلقة بالفعل")
    row.status = "closed"  # type: ignore[assignment]
    row.closed_at = func.now()
    audit(db, user, "close", "hr_review_cycle", row, f"إغلاق دورة تقييم {row.name}")
    db.commit()
    db.refresh(row)
    return row


@router.post("/review-cycles/{cycle_id}/reviews", response_model=schemas.HrReviewOut, status_code=status.HTTP_201_CREATED)
def create_performance_review(cycle_id: int, payload: schemas.HrReviewCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    cycle = _cycle_or_404(db, cycle_id)
    if cycle.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "دورة التقييم مغلقة — لا تقييمات جديدة")
    emp = _employee_or_404(db, payload.employee_id)
    if emp.id and emp.status == "terminated":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لا تقييم لموظف منتهي الخدمة")
    dup = (
        db.query(models.HrPerformanceReview)
        .filter(
            models.HrPerformanceReview.company_id == db.info["company_id"],
            models.HrPerformanceReview.cycle_id == cycle_id,
            models.HrPerformanceReview.employee_id == payload.employee_id,
        )
        .first()
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "الموظف مقيَّم بالفعل في هذه الدورة — عدّل التقييم القائم")
    row = models.HrPerformanceReview(
        company_id=db.info["company_id"],
        cycle_id=cycle_id,
        employee_id=payload.employee_id,
        quality=payload.quality,
        commitment=payload.commitment,
        teamwork=payload.teamwork,
        initiative=payload.initiative,
        comment=payload.comment,
        reviewed_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_performance_review", row, f"تقييم {emp.code} في دورة {cycle.name} · الدرجة {row.score}")
    db.commit()
    db.refresh(row)
    return row


@router.get("/review-cycles/{cycle_id}/reviews", response_model=List[schemas.HrReviewOut])
def list_cycle_reviews(cycle_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    _cycle_or_404(db, cycle_id)
    return (
        db.query(models.HrPerformanceReview)
        .filter(models.HrPerformanceReview.company_id == db.info["company_id"], models.HrPerformanceReview.cycle_id == cycle_id)
        .order_by(models.HrPerformanceReview.id.desc())
        .all()
    )


@router.patch("/performance-reviews/{review_id}", response_model=schemas.HrReviewOut)
def update_performance_review(review_id: int, payload: schemas.HrReviewUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = (
        db.query(models.HrPerformanceReview)
        .filter(models.HrPerformanceReview.company_id == db.info["company_id"], models.HrPerformanceReview.id == review_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التقييم غير موجود")
    cycle = _cycle_or_404(db, int(row.cycle_id))  # type: ignore[arg-type]
    if cycle.status == "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "دورة التقييم مغلقة — لا تعديل")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(row, field, value)
    audit(db, user, "update", "hr_performance_review", row, f"تعديل تقييم · الدرجة الآن {row.score}")
    db.commit()
    db.refresh(row)
    return row


@router.get("/performance-reviews", response_model=List[schemas.HrReviewOut])
def list_performance_reviews(
    response: Response,
    employee_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    q = db.query(models.HrPerformanceReview).filter(models.HrPerformanceReview.company_id == db.info["company_id"])
    if employee_id:
        q = q.filter(models.HrPerformanceReview.employee_id == employee_id)
    return paginate(q, response, skip, limit, models.HrPerformanceReview.id.desc())


# =====================================================================
# S6 — التدريب: دورات + تسجيل موظفين + إنجاز
# =====================================================================

def _training_or_404(db: Session, training_id: int) -> models.HrTraining:
    row = (
        db.query(models.HrTraining)
        .filter(models.HrTraining.company_id == db.info["company_id"], models.HrTraining.id == training_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الدورة التدريبية غير موجودة")
    return row


def _enrollment_or_404(db: Session, enrollment_id: int) -> models.HrTrainingEnrollment:
    row = (
        db.query(models.HrTrainingEnrollment)
        .filter(models.HrTrainingEnrollment.company_id == db.info["company_id"], models.HrTrainingEnrollment.id == enrollment_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التسجيل غير موجود")
    return row


@router.post("/trainings", response_model=schemas.HrTrainingOut, status_code=status.HTTP_201_CREATED)
def create_training(payload: schemas.HrTrainingCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    if payload.to_date < payload.from_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نهاية الدورة يجب أن تكون بعد بدايتها")
    row = models.HrTraining(
        company_id=db.info["company_id"],
        code=unique_code(db, models.HrTraining, db.info["company_id"], payload.title, "TRN"),
        title=payload.title.strip(),
        provider=payload.provider,
        location=payload.location,
        from_date=payload.from_date,
        to_date=payload.to_date,
        cost=payload.cost,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_training", row, f"دورة تدريب {row.title}")
    db.commit()
    db.refresh(row)
    return row


@router.get("/trainings", response_model=List[schemas.HrTrainingOut])
def list_trainings(response: Response, skip: int = 0, limit: int = 100, db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    q = db.query(models.HrTraining).filter(models.HrTraining.company_id == db.info["company_id"])
    rows = paginate(q, response, skip, limit, models.HrTraining.id.desc())
    counts = dict(
        db.query(models.HrTrainingEnrollment.training_id, func.count(models.HrTrainingEnrollment.id))
        .filter(models.HrTrainingEnrollment.company_id == db.info["company_id"], models.HrTrainingEnrollment.training_id.in_([t.id for t in rows] or [0]))
        .group_by(models.HrTrainingEnrollment.training_id)
        .all()
    )
    return [schemas.HrTrainingOut.model_validate(t, update={"enrollments_count": counts.get(t.id, 0)}) for t in rows]


@router.patch("/trainings/{training_id}", response_model=schemas.HrTrainingOut)
def update_training(training_id: int, payload: schemas.HrTrainingUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _training_or_404(db, training_id)
    data = payload.model_dump(exclude_unset=True)
    from_date = data.get("from_date", row.from_date)
    to_date = data.get("to_date", row.to_date)
    if from_date and to_date and to_date < from_date:  # type: ignore[operator]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "نهاية الدورة يجب أن تكون بعد بدايتها")
    for field, value in data.items():
        setattr(row, field, value)
    audit(db, user, "update", "hr_training", row, f"تعديل دورة تدريب {row.code}")
    db.commit()
    db.refresh(row)
    return row


@router.post("/trainings/{training_id}/enrollments", response_model=schemas.HrEnrollmentOut, status_code=status.HTTP_201_CREATED)
def create_enrollment(training_id: int, payload: schemas.HrEnrollmentCreate, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    training = _training_or_404(db, training_id)
    emp = _employee_or_404(db, payload.employee_id)
    if emp.status == "terminated":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لا تسجيل لموظف منتهي الخدمة")
    dup = (
        db.query(models.HrTrainingEnrollment)
        .filter(
            models.HrTrainingEnrollment.company_id == db.info["company_id"],
            models.HrTrainingEnrollment.training_id == training_id,
            models.HrTrainingEnrollment.employee_id == payload.employee_id,
        )
        .first()
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "الموظف مسجَّل في هذه الدورة بالفعل")
    row = models.HrTrainingEnrollment(
        company_id=db.info["company_id"],
        training_id=training_id,
        employee_id=payload.employee_id,
        created_by=user.id,
    )
    db.add(row)
    audit(db, user, "create", "hr_training_enrollment", row, f"تسجيل {emp.code} في {training.code}")
    db.commit()
    db.refresh(row)
    return row


@router.get("/trainings/{training_id}/enrollments", response_model=List[schemas.HrEnrollmentOut])
def list_enrollments(training_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    _training_or_404(db, training_id)
    return (
        db.query(models.HrTrainingEnrollment)
        .filter(models.HrTrainingEnrollment.company_id == db.info["company_id"], models.HrTrainingEnrollment.training_id == training_id)
        .order_by(models.HrTrainingEnrollment.id.desc())
        .all()
    )


@router.post("/enrollments/{enrollment_id}/complete", response_model=schemas.HrEnrollmentOut)
def complete_enrollment(enrollment_id: int, payload: schemas.HrEnrollmentDecision, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _enrollment_or_404(db, enrollment_id)
    if row.status != "enrolled":
        raise HTTPException(status.HTTP_409_CONFLICT, f"التسجيل في حالة «{row.status}» — القرارات متاحة للمسجَّلين فقط")
    row.status = "completed"  # type: ignore[assignment]
    row.completed_at = func.now()
    row.certificate_note = payload.certificate_note  # type: ignore[assignment]
    audit(db, user, "complete", "hr_training_enrollment", row, f"إتمام تدريب · {row.employee_code} · {row.training_title}")
    db.commit()
    db.refresh(row)
    return row


@router.post("/enrollments/{enrollment_id}/no-show", response_model=schemas.HrEnrollmentOut)
def no_show_enrollment(enrollment_id: int, db: Session = Depends(get_db), user: models.User = Depends(require_manager)):
    row = _enrollment_or_404(db, enrollment_id)
    if row.status != "enrolled":
        raise HTTPException(status.HTTP_409_CONFLICT, f"التسجيل في حالة «{row.status}»")
    row.status = "no_show"  # type: ignore[assignment]
    audit(db, user, "update", "hr_training_enrollment", row, f"غياب عن التدريب · {row.employee_code}")
    db.commit()
    db.refresh(row)
    return row


@router.get("/enrollments", response_model=List[schemas.HrEnrollmentOut])
def list_enrollments_all(
    response: Response,
    employee_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_manager),
):
    q = db.query(models.HrTrainingEnrollment).filter(models.HrTrainingEnrollment.company_id == db.info["company_id"])
    if employee_id:
        q = q.filter(models.HrTrainingEnrollment.employee_id == employee_id)
    return paginate(q, response, skip, limit, models.HrTrainingEnrollment.id.desc())


# =====================================================================
# S6 — لوحة HR التحليلية
# =====================================================================

@router.get("/analytics", response_model=schemas.HrAnalytics)
def hr_analytics(db: Session = Depends(get_db), _: models.User = Depends(require_manager)):
    """نظرة مجمعة: حضور الشهر، الإجازات، الدوران، الرواتب، التوظيف، الأداء/التدريب."""
    company_id = db.info["company_id"]
    today = date.today()
    month_start = today.replace(day=1)

    att_rows = (
        db.query(models.HrAttendance.status, func.count(models.HrAttendance.id))
        .filter(models.HrAttendance.company_id == company_id, models.HrAttendance.work_date >= month_start)
        .group_by(models.HrAttendance.status)
        .all()
    )
    att_counts = {s: int(c) for s, c in att_rows}
    att_total = sum(att_counts.values())
    att_present = att_counts.get("present", 0) + att_counts.get("late", 0)
    late_rows = (
        db.query(func.count(models.HrAttendance.id))
        .filter(models.HrAttendance.company_id == company_id, models.HrAttendance.work_date >= month_start, models.HrAttendance.late_minutes > 0)
        .scalar()
    )

    year_start = date(today.year, 1, 1)
    leave_pending = (
        db.query(func.count(models.HrLeaveRequest.id))
        .filter(models.HrLeaveRequest.company_id == company_id, models.HrLeaveRequest.status == "pending")
        .scalar()
    )
    leave_taken = (
        db.query(func.coalesce(func.sum(models.HrLeaveRequest.days), 0))
        .filter(models.HrLeaveRequest.company_id == company_id, models.HrLeaveRequest.status == "approved", models.HrLeaveRequest.from_date >= year_start)
        .scalar()
    )

    headcount = (
        db.query(func.count(models.HrEmployee.id))
        .filter(models.HrEmployee.company_id == company_id, models.HrEmployee.status.in_(("active", "probation")))
        .scalar()
    )
    terminated_12m = (
        db.query(func.count(models.HrEmployee.id))
        .filter(models.HrEmployee.company_id == company_id, models.HrEmployee.status == "terminated")
        .scalar()
    )

    last_run = (
        db.query(models.HrPayrollRun)
        .filter(models.HrPayrollRun.company_id == company_id, models.HrPayrollRun.status == "posted")
        .order_by(models.HrPayrollRun.year.desc(), models.HrPayrollRun.month.desc(), models.HrPayrollRun.id.desc())
        .first()
    )
    payroll_total = Decimal("0")
    payroll_slips = 0
    if last_run:
        payroll_total = (
            db.query(func.coalesce(func.sum(models.HrPayslip.net_pay), 0))
            .filter(models.HrPayslip.company_id == company_id, models.HrPayslip.run_id == last_run.id)
            .scalar()
        )
        payroll_slips = (
            db.query(func.count(models.HrPayslip.id))
            .filter(models.HrPayslip.company_id == company_id, models.HrPayslip.run_id == last_run.id)
            .scalar()
        )
    advances_active = (
        db.query(func.count(models.HrAdvance.id))
        .filter(models.HrAdvance.company_id == company_id, models.HrAdvance.status == "active")
        .scalar()
    )
    advances_outstanding = Decimal("0")
    for adv in (
        db.query(models.HrAdvance)
        .filter(models.HrAdvance.company_id == company_id, models.HrAdvance.status == "active")
        .all()
    ):
        consumed = (
            db.query(func.coalesce(func.sum(models.HrPayslipLine.amount), 0))
            .filter(models.HrPayslipLine.company_id == company_id, models.HrPayslipLine.advance_id == adv.id)
            .scalar()
        )
        advances_outstanding += max(Decimal(str(adv.amount)) - Decimal(str(consumed)), Decimal("0"))

    open_postings = (
        db.query(func.count(models.HrJobPosting.id))
        .filter(models.HrJobPosting.company_id == company_id, models.HrJobPosting.status == "open")
        .scalar()
    )
    stage_counts = dict(
        db.query(models.HrJobApplicant.stage, func.count(models.HrJobApplicant.id))
        .filter(models.HrJobApplicant.company_id == company_id)
        .group_by(models.HrJobApplicant.stage)
        .all()
    )

    review_rows = (
        db.query(models.HrPerformanceReview.quality, models.HrPerformanceReview.commitment, models.HrPerformanceReview.teamwork, models.HrPerformanceReview.initiative)
        .filter(models.HrPerformanceReview.company_id == company_id)
        .all()
    )
    review_avg = (sum(q + c + t + i for q, c, t, i in review_rows) / (len(review_rows) * 4)) if review_rows else None
    trainings_count = (
        db.query(func.count(models.HrTraining.id)).filter(models.HrTraining.company_id == company_id).scalar()
    )
    enroll_counts = dict(
        db.query(models.HrTrainingEnrollment.status, func.count(models.HrTrainingEnrollment.id))
        .filter(models.HrTrainingEnrollment.company_id == company_id)
        .group_by(models.HrTrainingEnrollment.status)
        .all()
    )

    return schemas.HrAnalytics(
        attendance={
            "month": month_start.isoformat(),
            "records": att_total,
            "present": att_present,
            "late": att_counts.get("late", 0),
            "absent": att_counts.get("absent", 0),
            "excused": att_counts.get("excused", 0),
            "late_minutes_cases": int(late_rows or 0),
            "attendance_rate": round(att_present / att_total * 100, 1) if att_total else 0.0,
        },
        leaves={
            "pending_requests": int(leave_pending or 0),
            "approved_days_this_year": Decimal(str(leave_taken or 0)),
            "headcount": int(headcount or 0),
            "terminated_count": int(terminated_12m or 0),
        },
        turnover={
            "headcount": int(headcount or 0),
            "terminated": int(terminated_12m or 0),
            "rate": round(int(terminated_12m or 0) / int(headcount or 0) * 100, 1) if headcount else 0.0,
        },
        payroll={
            "last_run_id": last_run.id if last_run else None,
            "last_run_period": f"{last_run.year}-{int(last_run.month):02d}" if last_run else None,
            "slips": int(payroll_slips or 0),
            "net_total": payroll_total,
            "advances_active": int(advances_active or 0),
            "advances_outstanding": advances_outstanding,
        },
        recruiting={
            "open_postings": int(open_postings or 0),
            "applicants_by_stage": {s: int(c) for s, c in stage_counts.items()},
        },
        talent={
            "avg_score": round(float(review_avg), 2) if review_avg is not None else None,
            "trainings": int(trainings_count or 0),
            "enrollments_completed": int(enroll_counts.get("completed", 0) or 0),
            "enrollments_enrolled": int(enroll_counts.get("enrolled", 0) or 0),
        },
    )
