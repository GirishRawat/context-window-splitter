; ModuleID = '/Users/girishrawat/Documents/Projects/context-window-splitter/corpus_src/bitwise.c'
source_filename = "/Users/girishrawat/Documents/Projects/context-window-splitter/corpus_src/bitwise.c"
target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-macosx15.0.0"

; Function Attrs: noinline nounwind ssp uwtable
define i32 @bit_tricks(i32 noundef %x) #0 {
entry:
  %x.addr = alloca i32, align 4
  %a = alloca i32, align 4
  %b = alloca i32, align 4
  store i32 %x, ptr %x.addr, align 4
  %0 = load i32, ptr %x.addr, align 4
  %1 = load i32, ptr %x.addr, align 4
  %xor = xor i32 %0, %1
  store i32 %xor, ptr %a, align 4
  %2 = load i32, ptr %a, align 4
  %3 = load i32, ptr %x.addr, align 4
  %or = or i32 %2, %3
  store i32 %or, ptr %b, align 4
  %4 = load i32, ptr %b, align 4
  ret i32 %4
}

; Function Attrs: noinline nounwind ssp uwtable
define i32 @redundant_arithmetic(i32 noundef %x) #0 {
entry:
  %x.addr = alloca i32, align 4
  %a = alloca i32, align 4
  %b = alloca i32, align 4
  %c = alloca i32, align 4
  store i32 %x, ptr %x.addr, align 4
  %0 = load i32, ptr %x.addr, align 4
  %add = add nsw i32 %0, 0
  store i32 %add, ptr %a, align 4
  %1 = load i32, ptr %a, align 4
  %mul = mul nsw i32 %1, 1
  store i32 %mul, ptr %b, align 4
  %2 = load i32, ptr %b, align 4
  %div = sdiv i32 %2, 1
  store i32 %div, ptr %c, align 4
  %3 = load i32, ptr %c, align 4
  ret i32 %3
}

; Function Attrs: noinline nounwind ssp uwtable
define i32 @redundant_logic(i32 noundef %x) #0 {
entry:
  %retval = alloca i32, align 4
  %x.addr = alloca i32, align 4
  store i32 %x, ptr %x.addr, align 4
  %0 = load i32, ptr %x.addr, align 4
  %cmp = icmp sgt i32 %0, 10
  br i1 %cmp, label %if.then, label %if.end3

if.then:                                          ; preds = %entry
  %1 = load i32, ptr %x.addr, align 4
  %cmp1 = icmp sgt i32 %1, 5
  br i1 %cmp1, label %if.then2, label %if.end

if.then2:                                         ; preds = %if.then
  %2 = load i32, ptr %x.addr, align 4
  %add = add nsw i32 %2, 1
  store i32 %add, ptr %retval, align 4
  br label %return

if.end:                                           ; preds = %if.then
  br label %if.end3

if.end3:                                          ; preds = %if.end, %entry
  %3 = load i32, ptr %x.addr, align 4
  store i32 %3, ptr %retval, align 4
  br label %return

return:                                           ; preds = %if.end3, %if.then2
  %4 = load i32, ptr %retval, align 4
  ret i32 %4
}

attributes #0 = { noinline nounwind ssp uwtable "frame-pointer"="non-leaf" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="apple-m1" "target-features"="+aes,+complxnum,+crc,+dotprod,+fp-armv8,+fp16fml,+fullfp16,+jsconv,+lse,+neon,+pauth,+ras,+rcpc,+rdm,+sha2,+sha3,+v8.1a,+v8.2a,+v8.3a,+v8.4a,+v8.5a,+v8a,+zcm,+zcz" }

!llvm.ident = !{!4}

!0 = !{i32 1, !"wchar_size", i32 4}
!1 = !{i32 8, !"PIC Level", i32 2}
!2 = !{i32 7, !"uwtable", i32 1}
!3 = !{i32 7, !"frame-pointer", i32 1}
!4 = !{!"clang version 18.1.8 (https://github.com/llvm/llvm-project.git 3b5b5c1ec4a3095ab096dd780e84d7ab81f3d7ff)"}
