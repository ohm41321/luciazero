[English](README.md) | **ภาษาไทย**

# Luciazero สำหรับ Claude Code & Codex CLI

[![npm](https://img.shields.io/npm/v/luciazero)](https://www.npmjs.com/package/luciazero)
[![CI](https://github.com/ohm41321/luciazero/actions/workflows/ci.yml/badge.svg)](https://github.com/ohm41321/luciazero/actions/workflows/ci.yml)
[![license](https://img.shields.io/github/license/ohm41321/luciazero)](LICENSE)

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia.png" width="300" alt="Lucia — มาสคอตของ Luciazero — กอดตุ๊กตาแมว">
</p>

Luciazero ทำให้ coding agent รันลูป `plan → change → verify → fix` ของตัวเองจนจบ แทนที่จะส่งงานที่ยังไม่ได้พิสูจน์กลับมาให้เรา กฎข้อแรกของมันไม่ใช่เรื่อง prompt:

> เสร็จ ต้องพิสูจน์ด้วยคำสั่ง ไม่ใช่ด้วยความเห็นของฉัน ถ้าไม่มีคำสั่ง verify — นั่นคือบั๊กแรกที่ต้องแก้

ทุกอย่างใน repo นี้ — doctrine 9 ข้อ, skill หกตัว, reviewer agent สายหักล้าง, enforcement hooks, eval harness — มีไว้เพื่อทำให้กฎข้อนี้เป็นจริงโดยไม่ต้องมีคนคอยดูทุกลูป

## หน้าตาเวลาใช้งานจริง

เอาต์พุตจริงของสคริปต์ที่ ship มา ไม่ใช่ mockup — GIF อัดจาก `docs/assets/statusline-demo.sh` ซึ่งขับ hook ตัวจริงผ่าน loop ทั้งวง (อัดซ้ำเองได้: `vhs docs/assets/demo.tape`):

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/statusline-demo.gif" width="720" alt="Enforcement pack ใน 15 วินาที: แก้ไฟล์ขึ้น unverified, จะจบ session โดน nudge, verify แดงขึ้น RED, แก้แล้วกลับเขียว">
</p>

statusline โชว์สถานะ verify บนหน้าจอตลอดเวลา:

```
Opus | ✎ unverified          # แก้โค้ดแล้ว ยังไม่รัน verify เลย
Opus | ✅ verify 3m           # verify ล่าสุดเขียว เมื่อ 3 นาทีก่อน
Opus | ❌ verify RED 40s      # verify ล่าสุดแดง — ลูปยังไม่จบ
```

จะจบ session ทั้งที่แก้โค้ดแล้วยังไม่ verify → โดนเตือนหนึ่งครั้ง:

```
Doctrine rule 1: edits were made but no verify command has run since the last
edit. Run the repo's verify command and quote its decisive line — or finish
anyway and say plainly that the change is unverified. (This nudge fires once.)
```

และใน strict mode (opt-in) verify ที่แดงจะ*บล็อก*การจบ session จริง ๆ พร้อมแนบหลักฐาน:

```
Strict verify gate: './test.sh' is RED. Fix it before finishing — or say
plainly that you are handing back a red state. Failing output:

test_totals ... FAIL: expected 14, got 8
```

## กันความพังแบบไหนบ้าง

ทุกโหมดความพังจับคู่กับกลไกที่ ship จริง ไม่ใช่คำสัญญา:

| โหมดความพัง | อะไรจับ |
|---|---|
| "เสร็จแล้ว!" โดยไม่เคยรัน verify | nudge ของ Stop hook; ใน strict mode verify แดงจะ block การจบ session พร้อม quote output ที่พัง |
| `cat test.sh` ถูกนับว่ารันเทสต์ | โหมด exact-match ของ `LUCIAZERO_VERIFY_CMD` |
| check ถูกลดความเข้ม ข้าม หรือลบเพื่อให้เขียว | doctrine กฎข้อ 3 บวก check-suppression guard (inert) ใน project settings ตัวอย่าง |
| เทสต์ใหม่ที่ผ่านทั้งแบบมีและไม่มี fix | `revert-probe.sh` — exit 1 คือเทสต์กลวง |
| scope หายเงียบ ๆ จากคำขอ | `/done` ขั้น 4: ทุกส่วนต้องส่งมอบหรือบอกชัดว่าตัดออกเพราะอะไร |
| ทางตันเดิมถูกไล่ซ้ำ session หน้า | ledger ของ `/retro` (`docs/lessons.md`, heuristics ข้าม repo) ป้อนเข้า `/debug` |

แถวที่เป็นกลไกถูก `test.sh` ทดสอบทุก push; แถวที่เป็น procedure คือสิ่งที่ eval harness มีไว้วัด

## ติดตั้ง

**Claude Code — plugin (แนะนำ)** ติดตั้งครั้งเดียวได้ครบ: skill ทั้งหก, agent `reviewer`, hook ติดตามการ verify และ doctrine:

```
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

จากนั้นรัน `/luciazero:luciazero-bootstrap` ใน repository ไหนก็ได้ (skill ของ plugin ใช้ namespace: `/luciazero:done`, `/luciazero:debug`, …) บอกกันตรง ๆ: การติดตั้ง plugin คือสิ่งที่เปิดใช้ hook ของมัน — ขั้นตอนติดตั้งนั้นแหละ*คือ*การ opt-in; doctrine โหลดผ่าน hook `SessionStart` เพราะ plugin เติมบรรทัด import ลง `CLAUDE.md` ไม่ได้ (ข้อความชุดเดียวกันที่ถูกคุมเพดานจำนวนคำ และจะเงียบเมื่อมีการติดตั้งแบบ classic อยู่ จึงไม่มีทางโหลดซ้ำสองรอบ) และไม่มี statusline เพราะ Claude Code ไม่ให้ plugin ตั้ง `statusLine`

**Agent ตัวไหนก็ได้ — เอาเฉพาะ skill** ผ่าน [vercel-labs/skills](https://github.com/vercel-labs/skills) ลง Claude Code, Codex, Cursor และอีก 70+ ตัว ไม่มี doctrine ไม่มี reviewer agent ไม่มี hook:

```
npx skills add ohm41321/luciazero
```

**ติดตั้งแบบ classic** ช่องทางอ้างอิง — ช่องทางเดียวที่มี statusline, การ import เข้า `CLAUDE.md`, health check `--status` และตัวติดตั้งฝั่ง Codex CLI รายละเอียดอยู่ใน section ถัด ๆ ไป:

```bash
npx luciazero               # Claude Code   (--with-hooks สำหรับ enforcement pack, --status)
npx luciazero codex         # Codex CLI     (ถอนด้วย npx luciazero uninstall)
```

`npx luciazero` เป็น wrapper บาง ๆ ที่ไม่มี lifecycle script — ไม่มีอะไรรันตอน npm install (`test.sh` บังคับข้อนี้ไว้) มันแค่เรียก bash installer ชุดเดิมที่ตรวจสอบได้ ตัวเดียวกับที่ได้จาก `git clone https://github.com/ohm41321/luciazero.git && ./install.sh` เลือกช่องทาง**เดียว** — plugin หรือ classic — เพื่อไม่ให้ hook ถูกต่อสายซ้ำสองชั้น อยากเห็นหลักฐานก่อนติดตั้ง? `./demo.sh` สร้าง repo ฝังบั๊กให้คุณแก้ใน session ของตัวเองแล้วให้ grader แบบ offline ตัดสิน

## ติดตั้งแล้วใช้ skill ไหนตอนไหน

ไม่ต้องท่องอะไร — doctrine กับ hook ทำงานเองอยู่เบื้องหลัง ส่วน skill มีไว้เรียกเฉพาะจังหวะ และก้าวแรกในทุก repository คือรัน `/luciazero-bootstrap` หนึ่งครั้ง เพื่อให้มีคำสั่ง verify ให้ทุกอย่างที่เหลือพิงได้ (ติดตั้งแบบ plugin ชื่อจะมี prefix: `/luciazero:done`, `/luciazero:debug`, …)

| จังหวะ | Skill | ทำอะไร |
|---|---|---|
| เข้า repository ครั้งแรก | `/luciazero-bootstrap` | หาหรือสร้างคำสั่ง verify, เพิ่ม smoke test 3–6 ตัว + ไฟล์ notes ของโปรเจกต์, พิสูจน์ว่า verify แดงได้จริง |
| บั๊กที่มองแวบแรกไม่ออก | `/debug` | reproduce ให้นิ่งก่อน, hypothesis ledger ที่ seed จากบทเรียนเก่า (`docs/lessons.md` + heuristics ข้าม repo), ปิดด้วย regression test ที่แดงก่อนแก้ |
| กำลังจะบอกว่า "เสร็จ" | `/done` | verify ระดับเต็มพร้อมยกบรรทัดชี้ขาด, อ่าน diff แบบผู้ไม่เชื่อ, เช็คความซื่อสัตย์ของ test ด้วย `revert-probe.sh`, รายงานฟอร์มตายตัว |
| ต้องหยุดทั้งที่งานยังไม่จบ | `/handoff` | เขียน capsule `HANDOFF.md`: เป้าหมาย, สถานะที่ verify แล้ว, คำสั่งถัดไปหนึ่งคำสั่งแบบพิมพ์ตามได้ |
| งานสาย "ทำให้เร็วขึ้น" | `/experiment` | ตั้ง metric + เกณฑ์ชนะก่อนแตะโค้ด, วัด baseline ซ้ำหลายรอบ, หนึ่งตัวแปรต่อรอบ, ตัวแพ้ถูก revert |
| หลังงานยากหรือ debug ยาว | `/retro` | route บทเรียนลง notes ของโปรเจกต์, ledger `docs/lessons.md` และ heuristics ข้าม repo; อ่าน stats log วินัยของตัวเอง |

agent `reviewer` ไม่ต้องเรียกชื่อเอง — `/done` จะ spawn ให้เมื่อ diff เสี่ยงพอ หรือพิมพ์ขอ "adversarial review" ตอนไหนก็ได้

## สิ่งที่ได้

ไม่มี dependency ไม่มี runtime (ใช้ python3 เฉพาะ enforcement pack ซึ่งเป็น opt-in):

| ชิ้นส่วน | หน้าที่ | โหลดเมื่อไหร่ |
|---|---|---|
| `claude/luciazero.md` | Doctrine — กฎ 9 ข้อ | ตลอดเวลา ทุกโปรเจกต์ ทุก session |
| `skills/luciazero-bootstrap/` | ขั้นตอนทำ repo ให้พร้อมสำหรับ agent (มาพร้อม `scripts/detect.sh`) | เมื่อเรียก |
| `skills/debug/` | ขั้นตอน debug แบบตั้ง hypothesis ก่อนแก้ | เมื่อเรียก |
| `skills/done/` | พิธีปิดงาน (มาพร้อม `scripts/revert-probe.sh`) | เมื่อเรียก |
| `skills/handoff/` | state capsule ส่งต่อให้ session/agent ถัดไป | เมื่อเรียก |
| `skills/experiment/` | โปรโตคอลวัดผลสำหรับงาน optimize | เมื่อเรียก |
| `skills/retro/` | เก็บเกี่ยวบทเรียนลง notes ของโปรเจกต์ | เมื่อเรียก |
| `claude/agents/reviewer.md` | Subagent ผู้ตรวจเชิงหักล้าง | เมื่อเรียก (ก่อนประกาศ "เสร็จ") |
| `claude/hooks/` | Enforcement pack — hook เตือน verify, strict gate แบบ opt-in, statusline | Opt-in |
| `eval/` | A/B harness — 6 task บั๊กฝัง, grader พิสูจน์ตัวเองได้ | รันเอง (เสียเงิน API) |
| `demo.sh` | เดโม 2 นาที — บั๊กฝัง, session ของคุณเอง, grader เป็นกลาง | รันเอง |

เทียบกับ superpowers, SuperClaude, proof-loop และของ built-in ใน harness — รวมทั้งจุดที่เขาทำได้ดีกว่า: [docs/comparison.md](docs/comparison.md)

## ติดตั้งแบบ classic & enforcement pack

`./install.sh` ทำสี่อย่าง: คัดลอก `claude/luciazero.md` → `~/.claude/luciazero.md`, skill ทั้งหก → `~/.claude/skills/`, reviewer agent → `~/.claude/agents/reviewer.md` (ถ้ามีฉบับที่คุณแก้เองจะ backup ให้ก่อน) และเติมบรรทัด `@luciazero.md` ลง `~/.claude/CLAUDE.md` มัน backup `CLAUDE.md` ก่อนแตะเสมอ รันซ้ำได้ปลอดภัย และไม่เขียนอะไรนอก `~/.claude/` เลย — สี่ขั้นตอนนี้ก็คือการติดตั้งมือทั้งหมดด้วย

### Enforcement pack (opt-in)

```bash
./install.sh --with-hooks    # ต้องมี python3
```

ต่อสคริปต์สองตัวเข้า `~/.claude/settings.json` (backup ให้ก่อน, merge แบบ additive และ idempotent): **Stop hook เตือน verify** — ถ้าแก้โค้ดแล้วไม่มีคำสั่งแนว verify รันเลยหลังการแก้ล่าสุด การจบ session จะโดนเตือนหนึ่งครั้งตามตัวอย่างข้างบน เตือนครั้งเดียว ไม่วนลูป และ fail open — กับ **statusline** (ถ้าคุณมีของตัวเองอยู่แล้ว มันจะไม่แตะ) Stop hook ยังจดหนึ่งบรรทัดต่อผลลัพธ์การจบ session (`stop-clean` / `nudge` / `strict-block`) ลง `luciazero-stats.log` ใน config dir — อยู่ในเครื่องเท่านั้น เพดาน ~250 บรรทัด fail-open — ให้ `/retro` อ่านแล้วแปลงช่องโหว่วินัยที่เกิดซ้ำเป็นบทเรียนที่บันทึกไว้

อะไรนับเป็น verify ตัดสินด้วย regex กว้าง ๆ (test.sh, pytest, `npm test`, `cargo test`, …) — override ได้ด้วย `LUCIAZERO_VERIFY_REGEX` หรือดีกว่านั้น ตั้งคำสั่งจริงของ repo ด้วย `LUCIAZERO_VERIFY_CMD` (เช่นในบล็อก `env` ของ `.claude/settings.local.json` ประจำ repo): ในโหมด exact จะนับเฉพาะคำสั่งที่*เป็น*หรือ*ขึ้นต้นด้วย*มันเท่านั้น `cat test.sh` จึงทำให้สถานะเขียวปลอมไม่ได้ การเขียนไฟล์เอกสาร (`*.md` และพวก — `LUCIAZERO_DOC_REGEX`) จะไม่ re-arm การเตือน เพราะ skill สายปิดงานล้วนเขียน notes *หลัง* verify เขียวรอบสุดท้าย hook `SessionStart` จะพิมพ์ pointer หนึ่งบรรทัดเมื่อโปรเจกต์มี capsule `HANDOFF.md` ค้างอยู่ (เตือนความเก่าเมื่อเกิน `LUCIAZERO_HANDOFF_STALE_DAYS` ค่าเริ่มต้น 7 วัน) — ชี้ตำแหน่งเท่านั้น ไม่เอาเนื้อหามาใส่

**Strict mode (opt-in ซ้อน opt-in)** ตั้ง `LUCIAZERO_STRICT_VERIFY_CMD` เป็นคำสั่ง verify *เร็ว*ของ repo — ใน settings **ส่วนตัว**เท่านั้น ห้ามอยู่ในไฟล์ที่ commit ข้อจำกัดที่บอกตรง ๆ: hook อ่านจาก environment variable และแยกไม่ออกว่า settings ชั้นไหนตั้งมันมา — `env` ใน `.claude/settings.json` ที่ commit มากับ repo ก็ไปถึงมันเช่นกัน — เพราะฉะนั้นให้ถือว่า repo ที่ ship ตัวแปรนี้มาเป็น repo ประสงค์ร้าย และลบตัวแปรนั้นทิ้งก่อนเริ่มทำงานใน repo นั้น เมื่อจะจบ session hook จะรันคำสั่งนั้นจริง ๆ (เว้นแต่สถานะเขียวอยู่แล้วหลังการแก้ล่าสุด) แล้ว**บล็อกการจบ**เมื่อแดง พร้อมยกเอาต์พุตที่พังให้ดู มี hard timeout ตัดจบเด็ดขาดผ่าน `LUCIAZERO_STRICT_TIMEOUT` (ค่าเริ่มต้น 120 วินาที); ทุก error ภายใน — timeout, คำสั่งหาย, JSON พัง — ถอยกลับเป็นการเตือนธรรมดา ไม่มีทางกลายเป็นการบล็อก และ continuation หลังโดนบล็อกจะไม่โดนบล็อกซ้ำ (`stop_hook_active`): นี่คือลูกระนาดพร้อมหลักฐาน ไม่ใช่กำแพง

### ตรวจ อัปเดต ถอน

`./install.sh --status` คือ health check แบบอ่านอย่างเดียว: doctrine, skill, agent, บรรทัด import, เวอร์ชัน และ — เมื่อติดตั้ง enforcement pack — เช็คว่าไฟล์ hook รันได้*และถูกต่อสายจริง* (hook ออกแบบให้ fail open การติดตั้งที่พังจึงเงียบสนิทถ้าไม่มีตัวเช็ค) คืนค่าไม่เป็นศูนย์ถ้าชิ้นหลักหายไป อัปเดตด้วย `git pull && ./install.sh` (idempotent; sidecar เวอร์ชันทำให้ `--status` บอกได้เมื่อของที่ติดตั้งเก่ากว่า checkout) `./uninstall.sh` ลบสคริปต์และเก็บกวาดเฉพาะ entry ของเราใน settings โดยจับคู่ด้วย path เต็ม — รันจาก checkout ที่ใหม่อย่างน้อยเท่ากับตัวที่ใช้ติดตั้ง

### Codex CLI

`./install-codex.sh` (ถอนด้วย `./uninstall-codex.sh`) — เนื้อหาเดียวกัน source เดียว แปลงตอนติดตั้ง:

| ชิ้นส่วน | ไปอยู่ใน Codex เป็น |
|---|---|
| Doctrine | บล็อกคั่นด้วย marker ใน `~/.codex/AGENTS.md` (ติดตั้งซ้ำจะแทนที่ตรงที่เดิม) |
| Skill ทั้งหก | `~/.codex/skills/` — ฟอร์แมต `SKILL.md` เดียวกัน คัดลอกตรง ๆ |
| Agent `reviewer` | `~/.codex/skills/reviewer/` — Codex ไม่มี subagent จึง ship เป็น skill |
| Enforcement pack | ไม่ติดตั้ง — Codex ไม่มี hook/statusline |

เคารพ `CODEX_HOME`, backup `AGENTS.md`, idempotent, ไม่เขียนอะไรนอกไดเรกทอรีของ Codex — doctrine และ skill เขียนแบบเป็นกลางต่อแพลตฟอร์ม ข้อความชุดเดียวกันจึงใช้ได้ทั้งสอง CLI โดยไม่ต้องแปล

## Doctrine พูดว่าอะไร

กฎ 9 ข้อ 4 กลุ่ม ฉบับเต็มอยู่ใน `claude/luciazero.md`

**Ground truth** — "เสร็จ" ต้องพิสูจน์ด้วย exit code และการรันที่ไม่ได้เกิดขึ้นต้องรายงานตามนั้นตรง ๆ; ไม่มีคำสั่ง verify คือบั๊กแรก; ห้าม weaken การตรวจใด ๆ เพื่อให้เขียว

**Loop** — debug เริ่มด้วย hypothesis และคำสั่งที่จะหักล้างมัน ไม่ใช่การแก้โค้ด แล้ว reproduction กลายเป็น regression test; เข้า repo ที่ไม่คุ้นให้ orient ก่อนแก้ — CI คือแหล่งความจริงที่ซื่อสัตย์; ก้าวที่เล็กที่สุดที่ย้อนกลับได้; อ่าน diff สุดท้ายแบบผู้ไม่เชื่อ — diff เสี่ยงต้องผ่าน review เชิงหักล้างอิสระ

**Memory** — ห้ามเดินเข้าทางตันเดิมสองครั้ง: จดสิ่งที่โค้ดบอกเองไม่ได้ (null result, footgun) และอ่าน notes ของโปรเจกต์ก่อนทำงานในบริเวณที่ notes ครอบคลุม

**Autonomy** — หยุดแล้วถามด้วยคำถามที่ตัดสินได้ชัดเจน ก่อนการกระทำเดิมพันสูงหรือย้อนกลับไม่ได้ (ลบข้อมูล, deploy, production, public contract, เงิน, ออกนอก scope); อย่างอื่นเดินหน้าต่อ รวมข้อสงสัยเป็นคำถามคมคำถามเดียว; ทำให้ครบทั้ง scope และบอกชื่อสิ่งที่เว้นไว้

มันสั้นโดยตั้งใจ และ `test.sh` บังคับเพดานจำนวนคำของมัน เพราะทุกบรรทัดกินค่า context ทุก turn ของทุก session ข้อที่แค่เล่าซ้ำสิ่งที่ harness ปี 2026 บังคับเป็นค่า default อยู่แล้ว ถูกตัดออก; CHANGELOG บันทึกทุกการตัดพร้อม default ที่มันพึ่งพา

## Skill แต่ละตัวทำอะไร

`/luciazero-bootstrap` พา repository ผ่าน 6 เฟส: **detect** (รัน `scripts/detect.sh` สแกนหลักฐานในคำสั่งเดียว แล้วอ่าน config CI เอง — CI คือแหล่งความจริง; สคริปต์เสนอตัวเลือก ส่วน agent เป็นคนตัดสิน), **ตั้งคำสั่ง verify** (ใช้ตัวเดิมถ้ามี ไม่มีค่อยสร้างตัวจริงที่เล็กที่สุด: exit ไม่เป็นศูนย์เมื่อพัง รันจบเอง รัน offline และ*จับเวลาหนึ่งครั้ง* — ตัวเลขตัดสินว่าหนึ่งหรือสองระดับ; monorepo ให้ scope ระดับเร็ว), **smoke tests** (3–6 ตัวที่จับความพังระดับหายนะ — ไม่ใช่ coverage และบอกไว้ตรง ๆ), **guardrails** (เอาเฉพาะ hook ที่คุ้มค่าตัวเอง; ฝั่ง Codex เข้ารหัสเป็นคำสั่งใน `AGENTS.md` แทน), **notes ของโปรเจกต์** (เฉพาะสิ่งที่อ่านโค้ดแล้วไม่มีทางรู้) และ **พิสูจน์** (รันระดับเร็วสองครั้ง — เขียวที่ไม่ซ้ำคือ flake; พังบรรทัดที่ cover จริง ยืนยันว่าแดง แล้วกู้คืน) ทั้งหมด language-agnostic: มัน detect ไม่ใช่ assume

`/debug` ขยายกฎ hypothesis สำหรับบั๊กที่มองแวบแรกไม่ออก: reproduce ให้ deterministic ก่อน, ย่อ reproduction, จด hypothesis ledger ให้เห็น ๆ (แต่ละรายการระบุคำสั่งที่จะหักล้างมัน), เปลี่ยนหนึ่งตัวแปรต่อรอบ, revert การแก้ที่ไม่ผ่าน, ปิดงานด้วย regression test ที่แดงก่อนแก้และเขียวหลังแก้ ledger จะ seed ตัวเองจากประสบการณ์ที่บันทึกไว้ก่อน — grep อาการใน `docs/lessons.md` ของ repo และ `luciazero-heuristics.md` ข้าม repo ก่อนคิด hypothesis ใหม่; เจอของเก่าตรง = ขึ้นเป็น H1 แต่ยังต้องพิสูจน์

`/done` คือพิธีปิดงาน: verify ระดับเต็มพร้อมยกบรรทัดชี้ขาด, อ่าน diff สุดท้ายแบบผู้ไม่เชื่อ, review เชิงหักล้างอิสระเมื่อ diff สมควรได้, เช็ค scope โดยระบุชื่อสิ่งที่เว้นไว้ และฟอร์มรายงานตายตัว คำถามความซื่อสัตย์ของ test — *ถ้า revert การแก้ test ใหม่จะแดงไหม?* — มีกลไกให้ใช้จริง: `scripts/revert-probe.sh` ที่แถมมา checkout โค้ดเก่าลง git worktree ชั่วคราว วางเฉพาะไฟล์ test ที่เปลี่ยนทับลงไป รันคำสั่ง verify ของคุณที่นั่น แล้วกลับผล (exit 0/1/2 = กัดจริง/test หลอก/ประเมินไม่ได้)

`/handoff` เขียน state capsule (`HANDOFF.md`) เมื่อ session จบทั้งที่งานยังไม่จบ: เป้าหมาย, สถานะที่ verify แล้ว, คำสั่งถัดไปหนึ่งคำสั่งแบบพิมพ์ตามได้เลย, hypothesis ที่ยังเปิด/หักล้างแล้ว, กับระเบิดที่รู้ตำแหน่ง, และ section `Read first` — ชี้ว่า entry ไหนใน `docs/lessons.md` เกี่ยวกับงานที่ค้าง พร้อม copy heuristics ประจำเครื่องมาทั้งบรรทัด (capsule คือทางเดียวที่ของพวกนี้ข้ามเครื่องได้) session ถัดไป — หรือ harness อีกฝั่ง — อ่าน, ตาม pointer, verify ซ้ำกับ tree จริง, แล้วลบทิ้ง

`/experiment` คือโปรโตคอลวัดผลสำหรับงาน "ทำให้เร็วขึ้น": นิยาม metric และเกณฑ์ชนะก่อนแตะโค้ด, วัด baseline ซ้ำหลายรอบ, หนึ่งตัวแปรต่อหนึ่งการทดลอง, บันทึกคำตัดสินลง `docs/experiments.md` — ที่ซึ่ง null result มีค่าเท่าชัยชนะ และตัวที่แพ้ถูก revert ทันที

`/retro` ปิดลูปของกฎ*ห้ามเดินเข้าทางตันเดิมสองครั้ง*: หลังงานยากมันกรอง session เอาเฉพาะสิ่งที่**อ่านโค้ดแล้ว agent ในอนาคตไม่มีทางรู้** (null result, footgun, ความประหลาดของ environment), route บทเรียนที่จริงสำหรับ repo ลง notes ของโปรเจกต์ ส่วนข้อเท็จจริงเฉพาะเครื่องลง memory ของ harness (ไม่ commit เด็ดขาด), อัปเดต notes เดิมแทนการเขียนซ้ำ และลบ notes ที่ถูกพิสูจน์แล้วว่าผิด คลังเรียนรู้สามชั้นทำให้มันทบต้นข้ามเวลา: บั๊กที่ debug จบแล้วลง `docs/lessons.md` ของ repo ในรูปแบบตายตัวที่ grep ได้ (อาการ → สาเหตุ → proven-by → วิธีแก้) ซึ่ง `/debug` จะอ่านรอบหน้า; บทเรียนที่จริงทุก repository ลง `luciazero-heuristics.md` ใน config dir (บรรทัดละหนึ่งบทเรียน เพดานแข็ง 100 บรรทัด — ไฟล์ heuristics ที่โตไม่หยุดจะกลายเป็นภาษี context ที่ pack นี้เกิดมาเพื่อกันเอง); และ stats log ของ enforcement pack แปลง nudge ที่โดนซ้ำ ๆ เป็นบทเรียนพฤติกรรม การถอนการติดตั้งเก็บทั้งสามไฟล์ไว้ — มันคือข้อมูลที่เรียนรู้มา retro ที่ว่างเปล่าก็เป็น retro ที่ถูกต้อง — และความรู้เลิกระเหยไปตอน session จบ

## ด่านหักล้าง: agent `reviewer`

exit code จับ *ผ่านเทสต์แต่ผิด* ไม่ได้ diff ที่เสี่ยง doctrine จึงต้องการ review เชิงหักล้างอิสระ: บน Claude Code คำสั่ง `/code-review` ในตัวแรงกว่าและถูกเลือกก่อนเมื่อมี; agent `reviewer` ที่ ship มาคือ fallback แบบพกพา และเป็น reviewer เดียวบน Codex อ่านอย่างเดียว ถูกสั่งให้**หักล้าง**การแก้ รันบนโมเดลเดียวกับ thread หลัก (`model: inherit`) และรายงาน `No findings.` แทนการมโนหาเรื่อง

## บันทึกการออกแบบ

**ทำไมเป็นไฟล์ ไม่ใช่ hook** hook มีไว้บังคับของที่ mechanical และ deterministic; doctrine คือวิจารณญาณ และวิจารณญาณอยู่ใน context Claude Code re-inject `CLAUDE.md` หลัง compaction อยู่แล้ว — คันโยกกัน drift ตัวจริงคือทำ doctrine ให้เล็ก ซึ่ง `test.sh` บังคับไว้

**ทำไม doctrine กับ skill แยกกัน** doctrine ต้องถูกพอที่จะพกทุก turn; procedure ยาวและใช้เฉพาะจังหวะ จึงโหลดเมื่อเรียก รวมกันเมื่อไหร่คุณจะจ่ายค่า procedure ตลอดเวลา

**Plugin เข้ากับหลักนี้ยังไง** plugin ไม่มีทาง import ไฟล์เข้า `CLAUDE.md` ช่องทาง plugin จึงส่ง doctrine เป็น context ผ่าน `SessionStart` — ยอมรับได้เพราะข้อความถูกคุมเพดานจำนวนคำ และมี guard ให้เงียบเมื่อการติดตั้งแบบ classic import มันอยู่แล้ว ตัวติดตั้ง classic ยังเป็นช่องทางอ้างอิง; plugin ยอมสละ statusline และ `--status` เพื่อแลกกับการติดตั้งด้วยคำสั่งเดียวและการอัปเดตผ่าน marketplace

**Settings ของโปรเจกต์อยู่กับโปรเจกต์** `examples/project-settings.example.json` โชว์รูปแบบราย repo — allowlist สิทธิ์เพื่อไม่ให้ลูป verify สะดุด และ guard แบบ inert สำหรับกันการกดเงียบ check ซึ่ง mechanize กฎ "ห้าม weaken การตรวจเพื่อให้เขียว" คัดลอกไปใส่ `.claude/settings.json` ของ repo; อย่าเอาคำสั่งของโปรเจกต์ไปใส่ settings ส่วนกลาง

**Agentic CI เป็นลูปวินิจฉัยเท่านั้น** `examples/luciazero-ci.example.yml` (inert, มี REPLACE-ME กั้น) โพสต์การวินิจฉัยต้นเหตุของ agent ลง PR เมื่อ CI แดง มัน push หรือแก้โค้ดไม่ได้ (`contents: read`, allowlist ไม่มี Bash, ไม่มี credentials); สิทธิ์เขียนเดียวคือโพสต์คอมเมนต์วินิจฉัยที่จำกัดขนาด มันไม่ auto-fix: agent ที่แก้ CI แบบตาบอด ship การแก้ที่ดูสมเหตุสมผลแต่ผิด

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia-laptop.png" width="240" alt="Lucia นั่งไล่ eval harness บนโน้ตบุ๊ก">
</p>

**Setup วัดตัวเอง** `eval/` คือ A/B harness เล็ก ๆ: task บั๊กฝังชุดเดียวกัน รันแบบมีและไม่มี doctrine แล้ว grade แบบ offline ด้วยเกณฑ์พฤติกรรม หก task แต่ละตัวจิ้มกฎคนละข้อ — slugify (วินัย regression test), red-suite (แรงล่อให้บิด test เข้าหาบั๊ก), flaky-report (ทำความล้มเหลวแบบมา ๆ หาย ๆ ให้ deterministic), pipeline (แก้ต้นเหตุ vs แปะที่อาการ ตัดสินด้วย diff locality), merge-conflict (merge ค้างกลางทาง — ห้ามทำ feature ฝั่งใดฝั่งหนึ่งหายเงียบ ๆ), false-green (suite เขียวตั้งแต่ต้นแต่บั๊กอยู่นอก coverage — กับดัก false done) `--with-lessons` เพิ่ม arm ที่สามที่ seed `docs/lessons.md` ของ task ไว้ล่วงหน้า วัดว่า learning layer คุ้มจริงไหม; ผลรันยังบันทึก duration, token และค่าใช้จ่ายต่อ run ด้วย CI พิสูจน์ grader ทุกตัวสามทางทุก push: `reference/` ต้องผ่าน, `project/` ที่ยังไม่แก้ต้องตก, tree โกง `gamed/` ต้องถูกปฏิเสธ `eval/run.sh --runs N` + `eval/report.sh` สร้างตาราง pass-rate รายเกณฑ์; ดู `eval/README.md` รวมทั้ง honesty box เรื่อง n น้อย

**ผลล่าสุด (2026-08-11)** หก task, doctrine vs bare (+ lessons เฉพาะสอง task ที่มี ledger), สองโมเดล — อัตราผ่านเกณฑ์รวม (all criteria), n = จำนวนรอบที่ valid ต่อ arm:

| โมเดล | doctrine | bare | Δ | lessons |
|---|---|---|---|---|
| **haiku** · n=10 | **36/60 (60%)** | **27/60 (45%)** | **+15pp** | 8/20 (40%) |
| **sonnet** · n=5 | **28/30 (93%)** | **17/30 (56%)** | **+37pp** | 10/10 (100%) |

แยกตาม task เรียงตาม Δ ของ sonnet แต่ละ bar คือ arm หนึ่งย่อเป็นสเกล 10 ช่อง — ช่องทึบ = รอบที่ผ่านทุกเกณฑ์:

**sonnet · n=5 ต่อ arm**

| task | doctrine | bare | Δ | lessons |
|---|---|---|---|---|
| slugify | `██████████` 5/5 | `··········` 0/5 | **+100pp** | – |
| merge-conflict | `██████····` 3/5 | `··········` 0/5 | **+60pp** | – |
| pipeline | `██████████` 5/5 | `██████····` 3/5 | **+40pp** | `██████████` 5/5 |
| false-green | `██████████` 5/5 | `████████··` 4/5 | **+20pp** | `██████████` 5/5 |
| flaky-report | `██████████` 5/5 | `██████████` 5/5 | +0pp | – |
| red-suite | `██████████` 5/5 | `██████████` 5/5 | +0pp | – |
| **รวม** | **28/30 (93%)** | **17/30 (56%)** | **+37pp** | **10/10 (100%)** |

**haiku · n=10 ต่อ arm**

| task | doctrine | bare | Δ | lessons |
|---|---|---|---|---|
| slugify | `███·······` 3/10 | `··········` 0/10 | **+30pp** | – |
| merge-conflict | `█·········` 1/10 | `··········` 0/10 | **+10pp** | – |
| pipeline | `████······` 4/10 | `··········` 0/10 | **+40pp** | `█·········` 1/10 |
| false-green | `████████··` 8/10 | `███████···` 7/10 | **+10pp** | `███████···` 7/10 |
| flaky-report | `██████████` 10/10 | `██████████` 10/10 | +0pp | – |
| red-suite | `██████████` 10/10 | `██████████` 10/10 | +0pp | – |
| **รวม** | **36/60 (60%)** | **27/60 (45%)** | **+15pp** | **8/20 (40%)** |

Haiku รัน 10 รอบ ไม่มี infrastructure fail เลย Sonnet รัน 5 รอบ; รอบที่ 5 OAuth session หมดอายุกลางคัน ทำให้แปด arm (merge-conflict/bare, pipeline ทั้งสาม arm, red-suite สอง arm, slugify สอง arm) ออกมาเป็น INVALID หลัง re-auth แล้วรันซ้ำจนครบ ตอนนี้ทุก arm ของ sonnet จึงอยู่ที่ n=5 และไม่เหลือแถว invalid แปดรอบที่รันเสริมนี้รันบน Windows/Git Bash บน commit เดียวกัน — task และ grader ชุดเดียวกัน แต่คนละ OS กับอีก 62 แถว แถวของ sonnet รายงาน modelUsage เป็น claude-sonnet-5 บวก claude-haiku-4-5 (subtask รันบน haiku) ยังไม่ได้วัด opus — วางแผนจะเพิ่มเป็นบล็อกโมเดลที่สามในอนาคต Δ คือ doctrine − bare แบบ floor เรนเดอร์ใหม่ได้ทุกเมื่อด้วย `eval/report.sh results-haiku.jsonl` / `eval/report.sh results-sonnet.jsonl`; honesty box ใน `eval/README.md` ยังใช้ — n น้อย เปรียบเทียบ rate อย่าเทียบรอบเดียว

## ความปลอดภัย

hook รันคำสั่งบนเครื่องคุณโดยอัตโนมัติ ไฟล์ settings ตัวอย่าง inert โดยออกแบบ — ทุก hook ในนั้นถูก comment ไว้และต้องแก้เองก่อนจึงจะทำอะไร อ่าน hook ทุกตัวก่อนเปิดใช้ และอย่าเปิด hook ที่ push, deploy, ลบ หรือเขียนนอก repository

## การพัฒนา repo นี้

`./test.sh` คือคำสั่ง verify ของ repo นี้เอง — doctrine บอกว่าไม่มีคำสั่ง verify คือบั๊กแรก repo นี้จึงต้องผ่านกฎของตัวเอง มันครอบคลุม shell syntax + shellcheck, state machine ของ hook (รวม strict gate), manifest ของ plugin + npm, grader ทุกตัวพิสูจน์ว่าแดงได้ *และ*เขียวได้ *และ*กันโกง, `revert-probe.sh` ใน git fixture ชั่วคราว, `demo.sh` และ cycle ติดตั้ง → ติดตั้งซ้ำ → ถอน ครบทั้งสอง harness ใน config dir แบบ sandbox — ไม่แตะ `~/.claude/` หรือ `~/.codex/` จริงของคุณเด็ดขาด CI รันทุก push; การ tag `vX.Y.Z` เผยแพร่ GitHub Release ดู `CONTRIBUTING.md` และ [docs/publishing.md](docs/publishing.md)

```
$ ./test.sh
PASS  all checks green
```

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia-cheer.png" width="240" alt="Lucia ฉลองเทสต์เขียวครบทุกด่าน">
</p>

## ผลิตภัณฑ์ในเครือ & สนับสนุน

Luciazero ใช้มาสคอตร่วมกับ [Lucia](https://lucia-discord-bot.vercel.app) — Discord bot ภาษาไทยที่มี AI chat, เปิดเพลง, มินิเกม และระบบสะสมการ์ดกาชา

ถ้า Luciazero ช่วยประหยัดรอบ review ของคุณได้ [สนับสนุนโปรเจกต์ได้ที่นี่](https://easydonate.app/itsathitz) 💚

## License

[MIT](LICENSE)
