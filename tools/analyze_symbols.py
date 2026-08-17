#!/usr/bin/env python3
"""
analyze_symbols.py — evidence-driven symbol discovery for Mega Man 8 (SLUS-00453).

Reads the headerless boot-EXE dump plus the recompiler's own function-boundary
manifest, and derives function names from evidence that is IN THE BINARY —
never from pattern-matching guesswork:

  1. BIOS call thunks       li $tN,0xA0/B0/C0 ; jr $tN ; li $t1,funcnum
                            -> the exact documented kernel entry (psx-spx).
  2. String cross-refs      lui/addiu(ori) pairs that compute the address of a
                            NUL-terminated ASCII literal. Psy-Q's libraries ship
                            their own debug/format strings ("ResetGraph(%d)...",
                            "CdlSetmode", RCS "$Id: sys.c,v ..." tags), so a
                            function that references one is that library routine.
                            Capcom's own messages ("PLAYER LOAD %x") name game code.
  3. MMIO access            loads/stores to 0x1F80xxxx classify a function's
                            subsystem (GPU / SPU / CD / SIO / DMA / IRQ / timer).
  4. COP2 usage             GTE instructions mark geometry code.
  5. Call graph             callers/callees, used to propagate and to rank.

Output is a report plus (with --write) two DIFFERENT artifacts — they are not
interchangeable (psxrecomp/docs/SYMBOLS.md and recompiler/src/annotations.cpp):

  * `symbols.toml` -> tools/sync_symbols.py -> psx_symbols.h. Host-side
    `PSX_FN_<name>` macros only. It does NOT rename the generated C; the
    recompiler never reads it (function names are always `func_%08X`).
  * `annotations/SLUS_004.53_annotations.csv` -> read by psxrecomp-game itself,
    emitted as `/* [NOTE] ... */` above the matching function in generated C.
    THIS is what makes the generated source readable.

`status` uses the vocabulary SYMBOLS.md documents — `guessed | confirmed | hot`:

    confirmed — the binary states it: a BIOS call thunk resolved through the
                documented kernel table, or a routine that references its own
                name as a debug literal.
    guessed   — inference from weaker evidence; do not build on it unverified.

Nothing here executes the game; it is pure static analysis of the local dump.
Usage:
    python3 tools/analyze_symbols.py                 # report only
    python3 tools/analyze_symbols.py --write         # update symbols.toml + annotations
    python3 tools/analyze_symbols.py --func 800D558C # disassemble/explain one function
    python3 tools/analyze_symbols.py --actor-struct  # decode the actor struct layout
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP = ROOT / "ghidra" / "SLUS_004.53_no_header.bin"
RANGES = ROOT / "generated" / "SLUS_004.53_full.ranges"
SYMBOLS_TOML = ROOT / "symbols.toml"
ANNOTATIONS = ROOT / "annotations" / "SLUS_004.53_annotations.csv"
BASE = 0x800C0000

# ---------------------------------------------------------------------------
# MIPS-I decode (little-endian, fixed 32-bit)
# ---------------------------------------------------------------------------
REG = ["zero","at","v0","v1","a0","a1","a2","a3","t0","t1","t2","t3","t4","t5","t6","t7",
       "s0","s1","s2","s3","s4","s5","s6","s7","t8","t9","k0","k1","gp","sp","fp","ra"]
SPECIAL = {0x00:"sll",0x02:"srl",0x03:"sra",0x04:"sllv",0x06:"srlv",0x07:"srav",
    0x08:"jr",0x09:"jalr",0x0C:"syscall",0x0D:"break",0x10:"mfhi",0x11:"mthi",
    0x12:"mflo",0x13:"mtlo",0x18:"mult",0x19:"multu",0x1A:"div",0x1B:"divu",
    0x20:"add",0x21:"addu",0x22:"sub",0x23:"subu",0x24:"and",0x25:"or",0x26:"xor",
    0x27:"nor",0x2A:"slt",0x2B:"sltu"}
OPC = {0x02:"j",0x03:"jal",0x04:"beq",0x05:"bne",0x06:"blez",0x07:"bgtz",
    0x08:"addi",0x09:"addiu",0x0A:"slti",0x0B:"sltiu",0x0C:"andi",0x0D:"ori",
    0x0E:"xori",0x0F:"lui",0x20:"lb",0x21:"lh",0x22:"lwl",0x23:"lw",0x24:"lbu",
    0x25:"lhu",0x26:"lwr",0x28:"sb",0x29:"sh",0x2A:"swl",0x2B:"sw",0x2E:"swr",
    0x30:"lwc0",0x32:"lwc2",0x38:"swc0",0x3A:"swc2"}
LOADS = {"lb","lh","lwl","lw","lbu","lhu","lwr","lwc2"}
STORES = {"sb","sh","swl","sw","swr","swc2"}
MEMOPS = LOADS | STORES


def decode(w: int, pc: int) -> dict:
    op = w >> 26
    d = {"raw": w, "pc": pc, "op": None, "rs": (w >> 21) & 31, "rt": (w >> 16) & 31,
         "rd": (w >> 11) & 31, "shamt": (w >> 6) & 31, "funct": w & 63,
         "imm": w & 0xFFFF, "simm": ((w & 0xFFFF) ^ 0x8000) - 0x8000,
         "target": (pc & 0xF0000000) | ((w & 0x3FFFFFF) << 2)}
    if w == 0:
        d["op"] = "nop"
    elif op == 0:
        d["op"] = SPECIAL.get(d["funct"])
    elif op == 1:
        d["op"] = {0: "bltz", 1: "bgez", 16: "bltzal", 17: "bgezal"}.get(d["rt"])
    elif op == 0x10:
        d["op"] = "cop0"
    elif op == 0x12:
        d["op"] = "cop2"
    else:
        d["op"] = OPC.get(op)
    return d


def disasm(d: dict) -> str:
    op, R = d["op"], REG
    if op is None:
        return f".word 0x{d['raw']:08X}"
    if op == "nop":
        return "nop"
    if op in ("j", "jal"):
        return f"{op} 0x{d['target']:08X}"
    if op == "jr":
        return f"jr ${R[d['rs']]}"
    if op == "jalr":
        return f"jalr ${R[d['rd']]}, ${R[d['rs']]}"
    if op == "lui":
        return f"lui ${R[d['rt']]}, 0x{d['imm']:04X}"
    if op in MEMOPS:
        return f"{op} ${R[d['rt']]}, {d['simm']}(${R[d['rs']]})"
    if op in ("addiu", "addi", "slti", "sltiu"):
        return f"{op} ${R[d['rt']]}, ${R[d['rs']]}, {d['simm']}"
    if op in ("andi", "ori", "xori"):
        return f"{op} ${R[d['rt']]}, ${R[d['rs']]}, 0x{d['imm']:04X}"
    if op in ("beq", "bne"):
        return f"{op} ${R[d['rs']]}, ${R[d['rt']]}, 0x{d['pc'] + 4 + d['simm'] * 4:08X}"
    if op in ("blez", "bgtz", "bltz", "bgez"):
        return f"{op} ${R[d['rs']]}, 0x{d['pc'] + 4 + d['simm'] * 4:08X}"
    if op in ("sll", "srl", "sra"):
        return f"{op} ${R[d['rd']]}, ${R[d['rt']]}, {d['shamt']}"
    if op == "cop2":
        return f"cop2 0x{d['raw'] & 0x1FFFFFF:07X}"
    if op in SPECIAL.values():
        return f"{op} ${R[d['rd']]}, ${R[d['rs']]}, ${R[d['rt']]}"
    return op


# ---------------------------------------------------------------------------
# PS1 kernel call tables (psx-spx). Used only for exact thunk naming.
# ---------------------------------------------------------------------------
A0 = {
 0x00:"open",0x01:"lseek",0x02:"read",0x03:"write",0x04:"close",0x05:"ioctl",
 0x06:"exit",0x07:"isatty",0x08:"getc",0x09:"putc",0x0A:"todigit",0x0B:"atof",
 0x0C:"strtoul",0x0D:"strtol",0x0E:"abs",0x0F:"labs",0x10:"atoi",0x11:"atol",
 0x12:"atob",0x13:"setjmp",0x14:"longjmp",0x15:"strcat",0x16:"strncat",
 0x17:"strcmp",0x18:"strncmp",0x19:"strcpy",0x1A:"strncpy",0x1B:"strlen",
 0x1C:"index",0x1D:"rindex",0x1E:"strchr",0x1F:"strrchr",0x20:"strpbrk",
 0x21:"strspn",0x22:"strcspn",0x23:"strtok",0x24:"strstr",0x25:"toupper",
 0x26:"tolower",0x27:"bcopy",0x28:"bzero",0x29:"bcmp",0x2A:"memcpy",
 0x2B:"memset",0x2C:"memmove",0x2D:"memcmp",0x2E:"memchr",0x2F:"rand",
 0x30:"srand",0x31:"qsort",0x32:"strtod",0x33:"malloc",0x34:"free",
 0x35:"lsearch",0x36:"bsearch",0x37:"calloc",0x38:"realloc",0x39:"InitHeap",
 0x3A:"SystemErrorExit",0x3B:"std_in_getchar",0x3C:"std_out_putchar",
 0x3D:"std_in_gets",0x3E:"std_out_puts",0x3F:"printf",
 0x40:"SystemErrorUnresolvedException",0x41:"LoadExeHeader",0x42:"LoadExeFile",
 0x43:"DoExecute",0x44:"FlushCache",0x45:"init_a0_b0_c0_vectors",
 0x46:"GPU_dw",0x47:"gpu_send_dma",0x48:"SendGP1Command",0x49:"GPU_cw",
 0x4A:"GPU_cwp",0x4B:"send_gpu_linked_list",0x4C:"gpu_abort_dma",
 0x4D:"GetGPUStatus",0x4E:"gpu_sync",0x51:"LoadAndExecute",
 0x54:"CdInit_a54",0x55:"_bu_init_a55",0x56:"CdRemove_a56",
 0x70:"_bu_init",0x71:"CdInit",0x72:"CdRemove",0x78:"CdAsyncSeekL",
 0x7C:"CdAsyncGetStatus",0x7E:"CdAsyncReadSector",0x81:"CdAsyncSetMode",
 0x90:"CdromIoIrqFunc1",0x91:"CdromDmaIrqFunc1",0x92:"CdromIoIrqFunc2",
 0x93:"CdromDmaIrqFunc2",0x94:"CdromGetInt5errCode",0x95:"CdInitSubFunc",
 0x96:"AddCDROMDevice",0x97:"AddMemCardDevice",0x98:"AddDuartTtyDevice",
 0x99:"AddDummyTtyDevice",0x9C:"SetConf",0x9D:"GetConf",0x9F:"SetMem",
 0xA0:"_boot",0xA1:"SystemError",0xA2:"EnqueueCdIntr",0xA3:"DequeueCdIntr",
 0xA5:"ReadSector",0xA6:"get_cd_status",0xB4:"GetSystemInfo",
}
B0 = {
 0x00:"alloc_kernel_memory",0x01:"free_kernel_memory",0x02:"init_timer",
 0x03:"get_timer",0x04:"enable_timer_irq",0x05:"disable_timer_irq",
 0x06:"restart_timer",0x07:"DeliverEvent",0x08:"OpenEvent",0x09:"CloseEvent",
 0x0A:"WaitEvent",0x0B:"TestEvent",0x0C:"EnableEvent",0x0D:"DisableEvent",
 0x0E:"OpenThread",0x0F:"CloseThread",0x10:"ChangeThread",0x12:"InitPad",
 0x13:"StartPad",0x14:"StopPad",0x15:"OutdatedPadInitAndStart",
 0x16:"OutdatedPadGetButtons",0x17:"ReturnFromException",
 0x18:"SetDefaultExitFromException",0x19:"SetCustomExitFromException",
 0x20:"UnDeliverEvent",0x32:"file_open",0x33:"file_seek",0x34:"file_read",
 0x35:"file_write",0x36:"file_close",0x37:"file_ioctl",0x38:"exit",
 0x39:"isFileConsole",0x3A:"file_getc",0x3B:"file_putc",0x3C:"std_in_getchar",
 0x3D:"std_out_putchar",0x3E:"std_in_gets",0x3F:"std_out_puts",
 0x40:"chdir",0x41:"FormatDevice",0x42:"firstfile",0x43:"nextfile",
 0x44:"FileRename",0x45:"FileDelete",0x46:"FileUndelete",0x47:"AddDevice",
 0x48:"RemoveDevice",0x49:"PrintInstalledDevices",0x4A:"InitCard",
 0x4B:"StartCard",0x4C:"StopCard",0x4D:"_card_info_subfunc",
 0x4E:"write_card_sector",0x4F:"read_card_sector",0x50:"allow_new_card",
 0x51:"Krom2RawAdd",0x53:"Krom2Offset",0x54:"GetLastError",
 0x55:"GetLastFileError",0x56:"GetC0Table",0x57:"GetB0Table",
 0x58:"get_bu_callback_port",0x59:"testdevice",0x5B:"ChangeClearPad",
 0x5C:"get_card_status",0x5D:"wait_card_status",
}
C0 = {
 0x00:"EnqueueTimerAndVblankIrqs",0x01:"EnqueueSyscallHandler",
 0x02:"SysEnqIntRP",0x03:"SysDeqIntRP",0x04:"get_free_EvCB_slot",
 0x05:"get_free_TCB_slot",0x06:"ExceptionHandler",
 0x07:"InstallExceptionHandlers",0x08:"SysInitMemory",
 0x09:"SysInitKernelVariables",0x0A:"ChangeClearRCnt",0x0C:"InitDefInt",
 0x12:"InstallDevices",0x13:"FlushStdInOutPut",0x15:"tty_cdevinput",
 0x16:"tty_cdevscan",0x17:"tty_circgetc",0x18:"tty_circputc",0x19:"ioabort",
 0x1A:"set_card_find_and_flush_cache",0x1C:"AdjustA0Table",
}
BIOS_TABLES = {0xA0: ("A0", A0), 0xB0: ("B0", B0), 0xC0: ("C0", C0)}

# MMIO regions -> subsystem tag (psx-spx).
MMIO = [
    (0x1F800000, 0x1F8003FF, "SCRATCH"),  # D-cache-as-scratchpad (fast RAM)
    (0x1F801040, 0x1F80105F, "SIO"),      # controller / memory card
    (0x1F801070, 0x1F801077, "IRQ"),
    (0x1F801080, 0x1F8010FF, "DMA"),
    (0x1F801100, 0x1F80112F, "TIMER"),
    (0x1F801800, 0x1F801803, "CDROM"),
    (0x1F801810, 0x1F801817, "GPU"),
    (0x1F801820, 0x1F801827, "MDEC"),
    (0x1F801C00, 0x1F801FFF, "SPU"),
]


def mmio_tag(addr: int) -> str | None:
    a = addr & 0x1FFFFFFF
    for lo, hi, tag in MMIO:
        if (lo & 0x1FFFFFFF) <= a <= (hi & 0x1FFFFFFF):
            return tag
    return None


# ---------------------------------------------------------------------------
# Image + string table
# ---------------------------------------------------------------------------
class Image:
    def __init__(self, path: Path, base: int):
        self.data = path.read_bytes()
        self.base = base
        self.end = base + len(self.data)

    def word(self, addr: int):
        o = addr - self.base
        if o < 0 or o + 4 > len(self.data):
            return None
        return struct.unpack_from("<I", self.data, o)[0]

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.end


def extract_strings(img: Image, minlen: int = 4) -> dict[int, str]:
    """address -> printable NUL-terminated string."""
    out, data, i, n = {}, img.data, 0, len(img.data)
    while i < n:
        b = data[i]
        if 0x20 <= b <= 0x7E:
            j = i
            while j < n and (0x20 <= data[j] <= 0x7E or data[j] in (9, 10, 13)):
                j += 1
            if j < n and data[j] == 0 and (j - i) >= minlen:
                out[img.base + i] = data[i:j].decode("ascii")
            i = j + 1
        else:
            i += 1
    return out


def load_functions(path: Path) -> list[tuple[int, int]]:
    """[(entry, length)] from the recompiler's code-range manifest."""
    entries, ranges = [], {}
    for line in path.read_text().splitlines():
        if line.startswith("F "):
            entries.append(int(line[2:].strip(), 16))
        elif line.startswith("R "):
            _, lo, ln = line.split()
            ranges[int(lo, 16)] = int(ln, 16)
    return [(e, ranges.get(e, 0)) for e in entries]


# ---------------------------------------------------------------------------
# Per-function analysis
# ---------------------------------------------------------------------------
class FuncInfo:
    __slots__ = ("addr", "size", "insns", "valid", "data_like", "strings",
                 "mmio", "gte", "calls", "bios", "callers", "syscalls",
                 "fmt_calls")

    def __init__(self, addr, size):
        self.addr, self.size = addr, size
        self.insns = 0
        self.valid = 0          # decodable instructions
        self.data_like = False
        self.strings: list[tuple[int, str]] = []
        self.mmio: set[str] = set()
        self.gte = 0
        self.calls: set[int] = set()
        self.bios: list[tuple[str, int, str]] = []   # (table, num, name)
        self.callers: set[int] = set()
        self.syscalls = 0
        self.fmt_calls: list[int] = []   # jal targets invoked with a string in $a0


def analyze(img: Image, strings: dict[int, str], funcs: list[tuple[int, int]]):
    infos: dict[int, FuncInfo] = {}
    str_addrs = strings
    for addr, size in funcs:
        fi = FuncInfo(addr, size)
        infos[addr] = fi
        n = max(size // 4, 1)
        regs: dict[int, int] = {}          # reg -> constant (upper set by lui)
        for k in range(n):
            pc = addr + k * 4
            w = img.word(pc)
            if w is None:
                break
            fi.insns += 1
            d = decode(w, pc)
            op = d["op"]
            if op is None:
                continue
            fi.valid += 1

            if op == "lui":
                regs[d["rt"]] = (d["imm"] << 16) & 0xFFFFFFFF
            elif op in ("addiu", "addi") and d["rs"] in regs:
                regs[d["rt"]] = (regs[d["rs"]] + d["simm"]) & 0xFFFFFFFF
            elif op == "ori" and d["rs"] in regs:
                regs[d["rt"]] = (regs[d["rs"]] | d["imm"]) & 0xFFFFFFFF
            elif op in ("addiu", "addi", "ori"):
                regs.pop(d["rt"], None)
            elif op == "jal":
                fi.calls.add(d["target"])
                # A string counts as REFERENCED only when it is handed to a
                # callee in an argument register. Merely holding the constant
                # proves nothing: BootEntry's BSS clear loop bounds its zero-fill
                # with 0x800F75B0, which happens to be where "VB Trans Error!!"
                # lives, and a looser rule named the entry point after it.
                for areg in (4, 5, 6, 7):          # $a0..$a3
                    v = regs.get(areg)
                    if v in str_addrs:
                        pair = (v, str_addrs[v])
                        if pair not in fi.strings:
                            fi.strings.append(pair)
                        if areg == 4:
                            fi.fmt_calls.append(d["target"])
                regs.clear()                # calls clobber caller-saved regs
            elif op == "cop2" or op in ("lwc2", "swc2"):
                fi.gte += 1
            elif op == "syscall":
                fi.syscalls += 1
            elif op in MEMOPS and d["rs"] in regs:
                eff = (regs[d["rs"]] + d["simm"]) & 0xFFFFFFFF
                t = mmio_tag(eff)
                if t:
                    fi.mmio.add(t)
            elif op in ("sll", "srl", "sra", "addu", "subu", "and", "or", "xor"):
                regs.pop(d["rd"], None)

            # A materialised hardware address is evidence on its own, whether or
            # not this function dereferences it: libspu/libcd hand the base to a
            # helper as an argument (lui a2,0x1F80 ; ori a2,a2,0x1C00 ; jal ...),
            # so requiring a load/store in the SAME function finds almost nothing.
            # (Strings are handled at the call site above — see the comment there.)
            for _r, v in regs.items():
                t = mmio_tag(v)
                if t:
                    fi.mmio.add(t)

        # BIOS thunk: li $tN,0xA0/B0/C0 ; jr $tN ; li $t1,num  (order varies)
        detect_bios_thunk(img, fi)

        # data heuristic: a "function" whose bytes are mostly a string literal
        if any(addr <= sa < addr + max(size, 4) for sa in str_addrs):
            if fi.valid < fi.insns * 0.6:
                fi.data_like = True

    for a, fi in infos.items():
        for t in fi.calls:
            if t in infos:
                infos[t].callers.add(a)
    return infos


def detect_bios_thunk(img: Image, fi: FuncInfo) -> None:
    """li $reg,0xA0|B0|C0 + jr $reg, with li $t1,<num> in the delay slot."""
    n = max(fi.size // 4, 1)
    if n > 8:
        return
    vec_reg: dict[int, int] = {}
    for k in range(n):
        pc = fi.addr + k * 4
        w = img.word(pc)
        if w is None:
            return
        d = decode(w, pc)
        if d["op"] in ("addiu", "addi") and d["rs"] == 0 and d["imm"] in BIOS_TABLES:
            vec_reg[d["rt"]] = d["imm"]
        elif d["op"] == "jr" and d["rs"] in vec_reg:
            vec = vec_reg[d["rs"]]
            dw = img.word(pc + 4)          # delay slot: li $t1, funcnum
            if dw is None:
                return
            dd = decode(dw, pc + 4)
            if dd["op"] in ("addiu", "addi") and dd["rs"] == 0 and dd["rt"] == 9:
                tbl, table = BIOS_TABLES[vec]
                num = dd["imm"]
                fi.bios.append((tbl, num, table.get(num, f"{tbl}({num:#04x})")))
            return


# ---------------------------------------------------------------------------
# Naming from evidence
# ---------------------------------------------------------------------------
# A literal that names its own routine. Matched against the strings a function
# references; the value is the symbol name to assign.
# Psy-Q's libraries log their own entry: "ResetGraph(%d)...",
# "ResetGraph:jtb=%08x,env=%08x", "CdInit: Init failed", "DrawSync(%d)...".
# Rather than enumerate every variant, take the leading identifier of any
# literal the routine passes to a printf-like callee. Requiring CamelCase (at
# least one lowercase character) rejects ALL-CAPS subsystem prefixes such as
# "CDROM:", "SPU:" and "DMA STATUS ERROR", which name a component, not a function.
SELF_NAME_RE = re.compile(r"^([A-Z][A-Za-z0-9_]{3,})[(:]")

# Literals that identify a routine but do not lead with its name.
SELF_NAMING = [
    (r"^This is not SEQ Data", "SsSeqOpen_checkFormat", "guessed"),
    (r"^Can't Open Sequence data", "SsSeqOpen_noSlot", "guessed"),
]


def self_name_from(s: str) -> str | None:
    m = SELF_NAME_RE.match(s)
    if not m:
        return None
    ident = m.group(1)
    if not any(c.islower() for c in ident):
        return None
    return ident

# Capcom shipped their debug menu in the retail build. A function's set of
# printf format strings describes it precisely; these map a distinctive literal
# to a name. Status stays "guessed": the string is evidence of what the routine
# PRINTS, which is strong but is not the routine declaring its own name.
GAME_NAMING = [
    (r"^ZENHAN LOAD |^KOUHAN LOAD |^MODULE LOAD ", "StageModuleLoad",
     "loads a stage's module set (zenhan/kouhan = first/second half, player, module)"),
    (r"^OVER LOAD ", "GameOverLoad", "game-over sequence loader"),
    (r"^VB Trans Error", "VabTransfer", "VAB (SPU sound bank) transfer + size check"),
    (r"^BASLUS-00453", "MemcardSaveFile",
     "builds/uses the memory-card filename BASLUS-00453 (BA + serial)"),
    (r"^MAINMENU", "DebugMainMenu", "debug menu root (MAINMENU/FLAGCHANGE/WORKVIEW/VABVIEW)"),
    (r"^SOUND TEST", "DebugSoundTest", "debug sound-test screen"),
    (r"^ILLEGAL SE NUM |^SE NUMBER:", "DebugSeTest", "debug sound-effect selector"),
    (r"^keyon:", "DebugKeyOnView", "debug SPU key-on / player-position view"),
    (r"^PLFX |^SHELL |^ENEMY ", "DebugObjectCounts",
     "debug object-slot view (player FX / shells / enemies)"),
    (r"^speedx:", "DebugActorVelocity", "debug view of an actor's speed/gravity fields"),
    (r"^dmg_id:", "DebugActorDamage",
     "debug view of an actor's damage fields (dmg_id/str/muteki=invincibility/life)"),
    (r"^scrptr:", "DebugActorPointers", "debug view of an actor's script/hit pointers"),
    (r"^beflag:", "DebugActorRoutines", "debug view of an actor's behaviour flag + routine indices"),
    (r"^settbl:", "DebugActorPosition", "debug view of an actor's set-table and X/Y position"),
    (r"^parts0:", "DebugActorParts", "debug view of an actor's parts slots"),
    (r"^GPU:%3d", "DebugGpuCount", "debug GPU primitive counter readout"),
    (r"^OBJ:%3d", "DebugObjCount", "debug object counter readout"),
]

def find_printf(infos: dict[int, "FuncInfo"]) -> int | None:
    """The callee most consistently invoked with a format string in $a0.

    Psy-Q's printf is not a BIOS thunk and carries no self-naming literal, so
    it can only be established from how the program calls it. Requires both a
    clear lead and a high fmt-to-total ratio so an ordinary helper that happens
    to take a string cannot win.
    """
    fmt = defaultdict(int)
    total = defaultdict(int)
    for fi in infos.values():
        for t in fi.fmt_calls:
            fmt[t] += 1
        for t in fi.calls:
            total[t] += 1
    if not fmt:
        return None
    best = max(fmt, key=lambda t: fmt[t])
    if fmt[best] < 20:
        return None
    if best not in infos:
        return None
    ratio = fmt[best] / max(len(infos[best].callers), 1)
    return best if ratio > 0.5 else None


C_IDENT_BAD = re.compile(r"[^A-Za-z0-9_]")


def c_ident(name: str) -> str:
    """sync_symbols.py hard-fails on a non-C-identifier name; force one."""
    s = C_IDENT_BAD.sub("_", name)
    if not s or not (s[0].isalpha() or s[0] == "_"):
        s = "_" + s
    return s


def toml_str(text: str) -> str:
    """Escape for a TOML basic string. Evidence notes quote the game's own
    literals, so unescaped `"` would make symbols.toml unparseable."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


def csv_note(text: str) -> str:
    """Make a note safe for annotations.cpp -> generated C.

    The recompiler pastes the note verbatim inside a C block comment and does
    NOT sanitize it (unlike sync_symbols.py), so an embedded `*/` would close
    the comment early and break the generated shard. Its line buffer is also
    1024 bytes, and anything past that is mis-parsed as a fresh record.
    """
    t = (text.replace("*/", "* /")
             .replace("\n", " ").replace("\r", " ").replace("\t", " "))
    t = " ".join(t.split())
    return t[:600]

# RCS $Id tags identify the Psy-Q translation unit a function was linked from.
ID_TAG = re.compile(r"\$Id: ([A-Za-z0-9_]+)\.c,v")


def derive_names(infos: dict[int, FuncInfo]) -> dict[int, tuple[str, str, str]]:
    """addr -> (name, status, evidence). Names are unique C identifiers."""
    raw: dict[int, tuple[str, str, str]] = {}

    # 1. BIOS thunks — exact, from the documented kernel tables.
    for a, fi in infos.items():
        if fi.bios:
            tbl, num, nm = fi.bios[0]
            raw[a] = (f"bios_{nm}", "confirmed",
                      f"BIOS call thunk -> {tbl}({num:#04x}) = {nm}")

    # 2. Routines that log their own name (Psy-Q libraries).
    for a, fi in infos.items():
        if a in raw:
            continue
        for _sa, s in fi.strings:
            ident = self_name_from(s)
            if ident:
                raw[a] = (ident, "confirmed",
                          f'logs its own name in the literal "{trim(s)}"')
                break
        if a in raw:
            continue
        for _sa, s in fi.strings:
            hit = next((t for t in SELF_NAMING if re.search(t[0], s)), None)
            if hit:
                raw[a] = (hit[1], hit[2],
                          f'references the literal "{trim(s)}"')
                break

    # 3. Game code, named from the debug output it prints.
    for a, fi in infos.items():
        if a in raw:
            continue
        for _sa, s in fi.strings:
            hit = next((t for t in GAME_NAMING if re.search(t[0], s)), None)
            if hit:
                raw[a] = (hit[1], "guessed",
                          f'{hit[2]}; prints "{trim(s)}"')
                break

    # 4. printf itself — established by call-site evidence, not a literal.
    pf = find_printf(infos)
    if pf and pf not in raw:
        raw[pf] = ("printf_lib", "confirmed",
                   "Psy-Q library printf: the overwhelming majority of its call "
                   "sites stage a format-string address in $a0")

    # sync_symbols.py emits one #define per entry with no duplicate check, so
    # two entries sharing a name would produce conflicting macros. Force
    # uniqueness by appending the address to collisions.
    seen: dict[str, int] = {}
    named: dict[int, tuple[str, str, str]] = {}
    for a in sorted(raw):
        nm, st, ev = raw[a]
        nm = c_ident(nm)
        if nm in seen:
            ev += f" (shares its evidence with 0x{seen[nm]:08X}; suffixed to stay unique)"
            nm = f"{nm}_{a:08X}"
        seen[nm] = a
        named[a] = (nm, st, ev)
    return named


def trim(s: str, n: int = 46) -> str:
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Reporting / emission
# ---------------------------------------------------------------------------
# Debug-menu routines that print an actor's fields one at a time. Each does
#   l{b,h,w}[u] $a1, OFFSET($s0) ; la $a0,"<field>:%..." ; jal printf
# so the load offsets ARE the struct layout. See docs/ACTOR_STRUCT.md.
ACTOR_PRINTERS = [0x801364D8, 0x8013658C, 0x801365D8, 0x80136728, 0x801367C4]
LOAD_TYPE = {"lb": ("s8", 1), "lbu": ("u8", 1), "lh": ("s16", 2),
             "lhu": ("u16", 2), "lw": ("u32", 4)}
FIELD_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_ ]*?)\s*:")


def actor_fields(img: Image, strings: dict[int, str],
                 sizes: dict[int, int]) -> dict[int, tuple[str, str, int, int]]:
    """offset -> (field, type, size, printer). Decoded, not guessed."""
    out: dict[int, tuple[str, str, int, int]] = {}
    for fn in ACTOR_PRINTERS:
        size = sizes.get(fn, 0)
        if not size:
            continue
        # These routines take the actor pointer in $a0 and copy it to $s0;
        # fall-through continuations reuse $s0 without re-establishing it.
        base, pending, lui = 16, [], None
        for k in range(size // 4):
            w = img.word(fn + k * 4)
            if w is None:
                break
            d = decode(w, fn + k * 4)
            op = d["op"]
            if op == "addu" and d["rs"] == 4 and d["rt"] == 0:
                base = d["rd"]
            elif op in LOAD_TYPE and d["rs"] == base and d["rt"] in (5, 6, 7):
                pending.append((d["simm"], LOAD_TYPE[op]))
            elif op == "lui":
                lui = (d["rt"], d["imm"] << 16)
            elif op in ("addiu", "addi") and lui and d["rs"] == lui[0] and d["rt"] == 4:
                s = strings.get((lui[1] + d["simm"]) & 0xFFFFFFFF)
                if s and pending:
                    for off, (ty, sz) in pending:
                        m = FIELD_RE.match(s)
                        nm = m.group(1).strip() if m else s.strip()[:12]
                        out.setdefault(off, (nm, ty, sz, fn))
                    pending = []
    return out


def cmd_actor(img, strings, infos, named, args):
    sizes = {a: fi.size for a, fi in infos.items()}
    fields = actor_fields(img, strings, sizes)
    if not fields:
        print("no actor fields decoded (are the debug printers in the manifest?)")
        return
    print(f"Mega Man 8 actor struct — {len(fields)} fields decoded from "
          f"{len(ACTOR_PRINTERS)} debug printers\n")
    print(f"{'offset':>8} {'size':>4}  {'type':<4}  {'field':<8}  printer")
    prev_end = None
    for off in sorted(fields):
        nm, ty, sz, fn = fields[off]
        if prev_end is not None and off > prev_end:
            print(f"  +0x{prev_end:02X} {off - prev_end:4}        "
                  f"{'(unknown)':<8}  —")
        print(f"  +0x{off:02X} {sz:4}  {ty:<4}  {nm:<8}  0x{fn:08X}")
        prev_end = off + sz
    print(f"\nknown extent: 0x{max(fields) + fields[max(fields)][2]:02X} bytes")


def cmd_report(img, strings, infos, named, args):
    total = len(infos)
    data_like = sum(1 for f in infos.values() if f.data_like)
    with_str = sum(1 for f in infos.values() if f.strings)
    thunks = sum(1 for f in infos.values() if f.bios)
    gte = sum(1 for f in infos.values() if f.gte)
    print(f"functions in manifest      : {total}")
    print(f"  look like DATA not code  : {data_like}")
    print(f"  reference a string       : {with_str}")
    print(f"  BIOS call thunks         : {thunks}")
    print(f"  use the GTE (COP2)       : {gte}")
    print(f"  named by this pass       : {len(named)}")
    print()
    bysub = defaultdict(int)
    for f in infos.values():
        for t in f.mmio:
            bysub[t] += 1
    print("hardware touched (functions with direct MMIO):")
    for t, c in sorted(bysub.items(), key=lambda kv: -kv[1]):
        print(f"  {t:<6} {c}")
    print()
    print("named symbols:")
    for a in sorted(named):
        nm, st, ev = named[a]
        print(f"  0x{a:08X}  {nm:<28} [{st}] {ev}")
    print()
    print("top callees (most-called functions — engine hot spots):")
    ranked = sorted(infos.values(), key=lambda f: -len(f.callers))[:15]
    for f in ranked:
        nm = named.get(f.addr, ("", "", ""))[0] or f"func_{f.addr:08X}"
        tags = ",".join(sorted(f.mmio)) or "-"
        print(f"  0x{f.addr:08X}  callers={len(f.callers):<4} size={f.size:<6} "
              f"mmio={tags:<12} {nm}")


def cmd_func(img, strings, infos, named, args):
    addr = int(args.func, 16)
    fi = infos.get(addr)
    if not fi:
        print(f"0x{addr:08X} is not a function entry in the manifest")
        near = [a for a in infos if a <= addr < a + max(infos[a].size, 4)]
        if near:
            print(f"  (inside func_{near[0]:08X})")
        return
    nm = named.get(addr, (f"func_{addr:08X}", "unnamed", ""))
    print(f"function 0x{addr:08X}  size={fi.size} ({fi.size // 4} insns)")
    print(f"  name     : {nm[0]}  [{nm[1]}]  {nm[2]}")
    print(f"  callers  : {len(fi.callers)}  callees: {len(fi.calls)}")
    if fi.mmio:
        print(f"  hardware : {', '.join(sorted(fi.mmio))}")
    if fi.gte:
        print(f"  GTE ops  : {fi.gte}")
    if fi.bios:
        print(f"  BIOS     : {fi.bios}")
    for sa, s in fi.strings:
        print(f'  string   : 0x{sa:08X} "{trim(s, 70)}"')
    print("  ---")
    for k in range(min(fi.size // 4, args.limit)):
        pc = addr + k * 4
        w = img.word(pc)
        if w is None:
            break
        d = decode(w, pc)
        extra = ""
        if d["op"] == "jal":
            t = d["target"]
            tn = named.get(t, ("", "", ""))[0]
            extra = f"   ; {tn}" if tn else ""
        print(f"  {pc:08X}: {w:08X}  {disasm(d)}{extra}")


TOML_HEADER = """\
# Mega Man 8 (SLUS-00453) — progressive symbol map.
#
# Discover -> label here -> use via PSX_FN_* (tools/sync_symbols.py -> psx_symbols.h).
# See psxrecomp/docs/SYMBOLS.md.
#
# status conventions for this project (see tools/analyze_symbols.py):
#   verified  the binary states it — a BIOS call thunk, or a routine that
#             references its own name as a debug literal. Trustworthy.
#   inferred  strong structural evidence, not a self-declaration.
#   guessed   weak/ambiguous — do not build on without checking.
#
# Entries below the marker are regenerated by tools/analyze_symbols.py --write.
# Hand-written entries go ABOVE it and are preserved.
"""
AUTO_MARKER = "# --- BEGIN auto-derived (tools/analyze_symbols.py) ---"
AUTO_MARKER_CSV = AUTO_MARKER

CSV_HEADER = """\
# Mega Man 8 (SLUS-00453) — function annotations.
#
# Format: 0xADDRESS, note      ('#' starts a comment line)
# The comma must follow the address IMMEDIATELY — "0xADDR , note" is silently
# dropped by recompiler/src/annotations.cpp.
#
# psxrecomp-game reads this file (relative to the project root) and emits each
# note as a /* [NOTE] ... */ comment above the matching function in
# generated/SLUS_004.53_full_*.c — this is what makes the generated C readable.
# An address that lands on a branch, a delay slot, or outside an emitted
# function is dropped silently.
#
# Hand-written rows go ABOVE the marker and are preserved by
# tools/analyze_symbols.py --write; rows below it are regenerated.\
"""


def split_manual(path: Path, marker: str, default_header: str) -> str:
    """Everything a human wrote above the auto marker (preserved verbatim)."""
    if not path.exists():
        return default_header.rstrip()
    txt = path.read_text()
    if marker in txt:
        return txt.split(marker)[0].rstrip()
    return txt.rstrip()


def manual_pcs(text: str) -> set[int]:
    """`pc = ...` values a human wrote above the marker."""
    out = set()
    for m in re.finditer(r"^\s*pc\s*=\s*\"?(0[xX][0-9A-Fa-f]+|\d+)\"?", text, re.M):
        try:
            out.add(int(m.group(1), 0) & 0xFFFFFFFF)
        except ValueError:
            pass
    return out


def cmd_write(img, strings, infos, named, args):
    manual = split_manual(SYMBOLS_TOML, AUTO_MARKER, TOML_HEADER)
    # sync_symbols.py emits `#define func_<PC> <name>` per entry with no
    # duplicate check, so re-listing a hand-written pc would define the same
    # alias twice with different names. Hand-written entries win.
    held = manual_pcs(manual)
    skipped = sorted(a for a in named if a in held)
    named = {a: v for a, v in named.items() if a not in held}
    lines = [manual, "", AUTO_MARKER, ""]
    for a in sorted(named):
        nm, st, ev = named[a]
        lines += ["[[func]]",
                  f"pc = 0x{a:08X}",
                  f'name = "{toml_str(nm)}"',
                  "emit = false",
                  f'status = "{toml_str(st)}"',
                  f'note = "{toml_str(ev)}"',
                  ""]
    SYMBOLS_TOML.write_text("\n".join(lines))
    print(f"wrote {SYMBOLS_TOML} ({len(named)} auto-derived entries)")
    for a in skipped:
        print(f"  kept hand-written entry for 0x{a:08X} (auto-name suppressed)")

    # Annotations CSV — this is the artifact that actually reaches generated C.
    # Format constraints come from recompiler/src/annotations.cpp:
    #   * the address must be followed IMMEDIATELY by ',' (a space kills the row)
    #   * '#' must be the first non-space char to comment a line
    #   * notes are pasted raw into a C block comment -> csv_note() defangs '*/'
    #   * 1024-byte line buffer -> csv_note() caps length
    rows = [split_manual(ANNOTATIONS, AUTO_MARKER_CSV, CSV_HEADER), AUTO_MARKER_CSV]
    n = 0
    for a in sorted(infos):
        fi = infos[a]
        bits = []
        if a in named:
            nm, st, ev = named[a]
            bits.append(f"{nm} [{st}] — {ev}")
        if fi.data_like:
            bits.append("classified DATA (string literals) rather than code")
        if fi.mmio:
            bits.append("touches " + "/".join(sorted(fi.mmio)))
        if fi.gte:
            bits.append(f"{fi.gte} GTE ops")
        if fi.strings and a not in named:
            shown = "; ".join(f'"{trim(s, 34)}"' for _sa, s in fi.strings[:3])
            bits.append(f"refs {shown}")
        if not bits:
            continue
        rows.append(f"0x{a:08X}, {csv_note('; '.join(bits))}")
        n += 1
    ANNOTATIONS.write_text("\n".join(rows) + "\n")
    print(f"wrote {ANNOTATIONS} ({n} annotated functions)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="update symbols.toml and the annotations CSV")
    ap.add_argument("--func", metavar="ADDR",
                    help="disassemble and explain one function (hex)")
    ap.add_argument("--strings", action="store_true", help="dump the string table")
    ap.add_argument("--actor-struct", action="store_true",
                    help="decode the actor struct from the debug-menu field printers")
    ap.add_argument("--limit", type=int, default=80,
                    help="max instructions for --func (default 80)")
    args = ap.parse_args()

    for p in (DUMP, RANGES):
        if not p.exists():
            sys.exit(f"missing {p}\n  (regenerate: see ghidra/instructions.txt / tools/regen.sh)")

    img = Image(DUMP, BASE)
    strings = extract_strings(img)
    funcs = load_functions(RANGES)
    infos = analyze(img, strings, funcs)
    named = derive_names(infos)

    if args.strings:
        for a in sorted(strings):
            print(f"{a:08X}\t{strings[a]}")
        return
    if args.actor_struct:
        cmd_actor(img, strings, infos, named, args)
        return
    if args.func:
        cmd_func(img, strings, infos, named, args)
        return
    cmd_report(img, strings, infos, named, args)
    if args.write:
        print()
        cmd_write(img, strings, infos, named, args)


if __name__ == "__main__":
    main()
