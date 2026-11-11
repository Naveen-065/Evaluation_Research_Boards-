# Pure protocol predicate shared by the bitmap tool and its unit test.
#
# The 512-bit response is exported through two VIO input probes.  A refresh can
# occasionally observe a transition-torn sample: result0 already contains the
# tagged READY decode while result1 is neither a legal progress nor completion
# record.  Operation 15 is complete only when READY and its BPD2 record agree.
proc bitmap_response_complete {op toggle status detail} {
 if {(($status>>15)&1)!=$toggle || !($status&512) || ($status&256)} {
  return 0
 }
 # A tagged, idle fault is a complete response too; let scan_command surface
 # its existing controller-fault diagnostic instead of waiting for BPD2.
 if {$status&1024} {
  return 1
 }
 if {$op==15 && (($detail>>224)&0xffffffff)!=0x42504432} {
  return 0
 }
 return 1
}
