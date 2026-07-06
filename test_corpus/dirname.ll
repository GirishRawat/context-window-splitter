; ModuleID = '/Users/girishrawat/Documents/Projects/context-window-splitter/sbase_src/dirname.c'
source_filename = "/Users/girishrawat/Documents/Projects/context-window-splitter/sbase_src/dirname.c"
target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-macosx15.0.0"

@argv0 = external global ptr, align 8
@__stdoutp = external global ptr, align 8
@.str = private unnamed_addr constant [9 x i8] c"<stdout>\00", align 1
@.str.1 = private unnamed_addr constant [16 x i8] c"usage: %s path\0A\00", align 1

; Function Attrs: noinline nounwind ssp uwtable
define i32 @main(i32 noundef %argc, ptr noundef %argv) #0 {
entry:
  %retval = alloca i32, align 4
  %argc.addr = alloca i32, align 4
  %argv.addr = alloca ptr, align 8
  %argc_ = alloca i8, align 1
  %argv_ = alloca ptr, align 8
  %brk_ = alloca i32, align 4
  store i32 0, ptr %retval, align 4
  store i32 %argc, ptr %argc.addr, align 4
  store ptr %argv, ptr %argv.addr, align 8
  %0 = load ptr, ptr %argv.addr, align 8
  %1 = load ptr, ptr %0, align 8
  store ptr %1, ptr @argv0, align 8
  %2 = load ptr, ptr %argv.addr, align 8
  %incdec.ptr = getelementptr inbounds ptr, ptr %2, i32 1
  store ptr %incdec.ptr, ptr %argv.addr, align 8
  %3 = load i32, ptr %argc.addr, align 4
  %dec = add nsw i32 %3, -1
  store i32 %dec, ptr %argc.addr, align 4
  br label %for.cond

for.cond:                                         ; preds = %for.inc41, %entry
  %4 = load ptr, ptr %argv.addr, align 8
  %arrayidx = getelementptr inbounds ptr, ptr %4, i64 0
  %5 = load ptr, ptr %arrayidx, align 8
  %tobool = icmp ne ptr %5, null
  br i1 %tobool, label %land.lhs.true, label %land.end

land.lhs.true:                                    ; preds = %for.cond
  %6 = load ptr, ptr %argv.addr, align 8
  %arrayidx1 = getelementptr inbounds ptr, ptr %6, i64 0
  %7 = load ptr, ptr %arrayidx1, align 8
  %arrayidx2 = getelementptr inbounds i8, ptr %7, i64 0
  %8 = load i8, ptr %arrayidx2, align 1
  %conv = sext i8 %8 to i32
  %cmp = icmp eq i32 %conv, 45
  br i1 %cmp, label %land.rhs, label %land.end

land.rhs:                                         ; preds = %land.lhs.true
  %9 = load ptr, ptr %argv.addr, align 8
  %arrayidx4 = getelementptr inbounds ptr, ptr %9, i64 0
  %10 = load ptr, ptr %arrayidx4, align 8
  %arrayidx5 = getelementptr inbounds i8, ptr %10, i64 1
  %11 = load i8, ptr %arrayidx5, align 1
  %conv6 = sext i8 %11 to i32
  %tobool7 = icmp ne i32 %conv6, 0
  br label %land.end

land.end:                                         ; preds = %land.rhs, %land.lhs.true, %for.cond
  %12 = phi i1 [ false, %land.lhs.true ], [ false, %for.cond ], [ %tobool7, %land.rhs ]
  br i1 %12, label %for.body, label %for.end44.loopexit

for.body:                                         ; preds = %land.end
  %13 = load ptr, ptr %argv.addr, align 8
  %arrayidx8 = getelementptr inbounds ptr, ptr %13, i64 0
  %14 = load ptr, ptr %arrayidx8, align 8
  %arrayidx9 = getelementptr inbounds i8, ptr %14, i64 1
  %15 = load i8, ptr %arrayidx9, align 1
  %conv10 = sext i8 %15 to i32
  %cmp11 = icmp eq i32 %conv10, 45
  br i1 %cmp11, label %land.lhs.true13, label %if.end

land.lhs.true13:                                  ; preds = %for.body
  %16 = load ptr, ptr %argv.addr, align 8
  %arrayidx14 = getelementptr inbounds ptr, ptr %16, i64 0
  %17 = load ptr, ptr %arrayidx14, align 8
  %arrayidx15 = getelementptr inbounds i8, ptr %17, i64 2
  %18 = load i8, ptr %arrayidx15, align 1
  %conv16 = sext i8 %18 to i32
  %cmp17 = icmp eq i32 %conv16, 0
  br i1 %cmp17, label %if.then, label %if.end

if.then:                                          ; preds = %land.lhs.true13
  %19 = load ptr, ptr %argv.addr, align 8
  %incdec.ptr19 = getelementptr inbounds ptr, ptr %19, i32 1
  store ptr %incdec.ptr19, ptr %argv.addr, align 8
  %20 = load i32, ptr %argc.addr, align 4
  %dec20 = add nsw i32 %20, -1
  store i32 %dec20, ptr %argc.addr, align 4
  br label %for.end44

if.end:                                           ; preds = %land.lhs.true13, %for.body
  store i32 0, ptr %brk_, align 4
  %21 = load ptr, ptr %argv.addr, align 8
  %arrayidx21 = getelementptr inbounds ptr, ptr %21, i64 0
  %22 = load ptr, ptr %arrayidx21, align 8
  %incdec.ptr22 = getelementptr inbounds i8, ptr %22, i32 1
  store ptr %incdec.ptr22, ptr %arrayidx21, align 8
  %23 = load ptr, ptr %argv.addr, align 8
  store ptr %23, ptr %argv_, align 8
  br label %for.cond23

for.cond23:                                       ; preds = %for.inc, %if.end
  %24 = load ptr, ptr %argv.addr, align 8
  %arrayidx24 = getelementptr inbounds ptr, ptr %24, i64 0
  %25 = load ptr, ptr %arrayidx24, align 8
  %arrayidx25 = getelementptr inbounds i8, ptr %25, i64 0
  %26 = load i8, ptr %arrayidx25, align 1
  %conv26 = sext i8 %26 to i32
  %tobool27 = icmp ne i32 %conv26, 0
  br i1 %tobool27, label %land.rhs28, label %land.end30

land.rhs28:                                       ; preds = %for.cond23
  %27 = load i32, ptr %brk_, align 4
  %tobool29 = icmp ne i32 %27, 0
  %lnot = xor i1 %tobool29, true
  br label %land.end30

land.end30:                                       ; preds = %land.rhs28, %for.cond23
  %28 = phi i1 [ false, %for.cond23 ], [ %lnot, %land.rhs28 ]
  br i1 %28, label %for.body31, label %for.end.loopexit

for.body31:                                       ; preds = %land.end30
  %29 = load ptr, ptr %argv_, align 8
  %30 = load ptr, ptr %argv.addr, align 8
  %cmp32 = icmp ne ptr %29, %30
  br i1 %cmp32, label %if.then34, label %if.end35

if.then34:                                        ; preds = %for.body31
  br label %for.end

if.end35:                                         ; preds = %for.body31
  %31 = load ptr, ptr %argv.addr, align 8
  %arrayidx36 = getelementptr inbounds ptr, ptr %31, i64 0
  %32 = load ptr, ptr %arrayidx36, align 8
  %arrayidx37 = getelementptr inbounds i8, ptr %32, i64 0
  %33 = load i8, ptr %arrayidx37, align 1
  store i8 %33, ptr %argc_, align 1
  %34 = load i8, ptr %argc_, align 1
  %conv38 = sext i8 %34 to i32
  switch i32 %conv38, label %sw.default [
  ]

sw.default:                                       ; preds = %if.end35
  call void @usage()
  br label %sw.epilog

sw.epilog:                                        ; preds = %sw.default
  br label %for.inc

for.inc:                                          ; preds = %sw.epilog
  %35 = load ptr, ptr %argv.addr, align 8
  %arrayidx39 = getelementptr inbounds ptr, ptr %35, i64 0
  %36 = load ptr, ptr %arrayidx39, align 8
  %incdec.ptr40 = getelementptr inbounds i8, ptr %36, i32 1
  store ptr %incdec.ptr40, ptr %arrayidx39, align 8
  br label %for.cond23, !llvm.loop !6

for.end.loopexit:                                 ; preds = %land.end30
  br label %for.end

for.end:                                          ; preds = %for.end.loopexit, %if.then34
  br label %for.inc41

for.inc41:                                        ; preds = %for.end
  %37 = load i32, ptr %argc.addr, align 4
  %dec42 = add nsw i32 %37, -1
  store i32 %dec42, ptr %argc.addr, align 4
  %38 = load ptr, ptr %argv.addr, align 8
  %incdec.ptr43 = getelementptr inbounds ptr, ptr %38, i32 1
  store ptr %incdec.ptr43, ptr %argv.addr, align 8
  br label %for.cond, !llvm.loop !8

for.end44.loopexit:                               ; preds = %land.end
  br label %for.end44

for.end44:                                        ; preds = %for.end44.loopexit, %if.then
  %39 = load i32, ptr %argc.addr, align 4
  %cmp45 = icmp ne i32 %39, 1
  br i1 %cmp45, label %if.then47, label %if.end48

if.then47:                                        ; preds = %for.end44
  call void @usage()
  br label %if.end48

if.end48:                                         ; preds = %if.then47, %for.end44
  %40 = load ptr, ptr %argv.addr, align 8
  %arrayidx49 = getelementptr inbounds ptr, ptr %40, i64 0
  %41 = load ptr, ptr %arrayidx49, align 8
  %call = call ptr @dirname(ptr noundef %41)
  %call50 = call i32 @puts(ptr noundef %call)
  %42 = load ptr, ptr @__stdoutp, align 8
  %call51 = call i32 @fshut(ptr noundef %42, ptr noundef @.str)
  ret i32 %call51
}

; Function Attrs: noinline nounwind ssp uwtable
define internal void @usage() #0 {
entry:
  %0 = load ptr, ptr @argv0, align 8
  call void (ptr, ...) @eprintf(ptr noundef @.str.1, ptr noundef %0)
  ret void
}

declare i32 @puts(ptr noundef) #1

declare ptr @dirname(ptr noundef) #1

declare i32 @fshut(ptr noundef, ptr noundef) #1

declare void @eprintf(ptr noundef, ...) #1

attributes #0 = { noinline nounwind ssp uwtable "frame-pointer"="non-leaf" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="apple-m1" "target-features"="+aes,+complxnum,+crc,+dotprod,+fp-armv8,+fp16fml,+fullfp16,+jsconv,+lse,+neon,+pauth,+ras,+rcpc,+rdm,+sha2,+sha3,+v8.1a,+v8.2a,+v8.3a,+v8.4a,+v8.5a,+v8a,+zcm,+zcz" }
attributes #1 = { "frame-pointer"="non-leaf" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="apple-m1" "target-features"="+aes,+complxnum,+crc,+dotprod,+fp-armv8,+fp16fml,+fullfp16,+jsconv,+lse,+neon,+pauth,+ras,+rcpc,+rdm,+sha2,+sha3,+v8.1a,+v8.2a,+v8.3a,+v8.4a,+v8.5a,+v8a,+zcm,+zcz" }

!llvm.ident = !{!5}

!0 = !{i32 2, !"SDK Version", [2 x i32] [i32 15, i32 5]}
!1 = !{i32 1, !"wchar_size", i32 4}
!2 = !{i32 8, !"PIC Level", i32 2}
!3 = !{i32 7, !"uwtable", i32 1}
!4 = !{i32 7, !"frame-pointer", i32 1}
!5 = !{!"clang version 18.1.8 (https://github.com/llvm/llvm-project.git 3b5b5c1ec4a3095ab096dd780e84d7ab81f3d7ff)"}
!6 = distinct !{!6, !7}
!7 = !{!"llvm.loop.mustprogress"}
!8 = distinct !{!8, !7}
