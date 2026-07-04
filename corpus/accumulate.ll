target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

define i32 @accumulate(i32 %n) {
entry:
  br label %loop.head

loop.head:
  %i = phi i32 [ 0, %entry ], [ %i.next, %loop.cont ]
  %acc = phi i32 [ 0, %entry ], [ %acc.next, %loop.cont ]
  %cond = icmp slt i32 %i, %n
  br i1 %cond, label %loop.body, label %exit

loop.body:
  %isodd = and i32 %i, 1
  %oddcmp = icmp eq i32 %isodd, 1
  br i1 %oddcmp, label %add.odd, label %add.even

add.odd:
  %a1 = add i32 %acc, %i
  br label %loop.cont

add.even:
  %tmp = add i32 %acc, 0
  %a2 = mul i32 %tmp, 1
  br label %loop.cont

loop.cont:
  %acc.next = phi i32 [ %a1, %add.odd ], [ %a2, %add.even ]
  %i.next = add i32 %i, 1
  br label %loop.head

exit:
  ret i32 %acc
}
