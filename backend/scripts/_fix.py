p = "backend/scripts/_patch.py"
ls = open(p).read().splitlines()
open(p, "w").write("\n".join(ls[:-1]) + "\n")
print("ok")