import re
raw_text = """```llvm
define i32 @main() {
  ret i32 0
}
```"""
match = re.search(r"(define\s+.*?^})", raw_text, re.DOTALL | re.MULTILINE)
print("Match:", match.group(1) if match else None)
