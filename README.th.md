[English](README.md) | **ภาษาไทย**

# Luciazero สำหรับ Claude Code และ Codex CLI

[![npm](https://img.shields.io/npm/v/luciazero)](https://www.npmjs.com/package/luciazero)
[![CI](https://github.com/ohm41321/luciazero/actions/workflows/ci.yml/badge.svg)](https://github.com/ohm41321/luciazero/actions/workflows/ci.yml)
[![license](https://img.shields.io/github/license/ohm41321/luciazero)](LICENSE)

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia.png" width="280" alt="Lucia — มาสคอตของ Luciazero">
</p>

Luciazero ทำให้ coding agent รันลูป `วางแผน → แก้ → ตรวจ → แก้ซ้ำ`
แทนการส่งงานกลับมาเพราะคิดเองว่าน่าจะเสร็จแล้ว

> งานเสร็จต้องพิสูจน์ด้วยคำสั่ง ไม่ใช่คำตัดสินของ agent
> ถ้ายังไม่มีคำสั่งตรวจ นั่นคือบั๊กแรก

ภายในมี [doctrine 9 ข้อ](claude/luciazero.md) ที่สั้น, skill แบบเรียกเมื่อจำเป็น
11 ตัว, hook ติดตามการ verify, reviewer ที่ route ตามความเสี่ยง และ eval harness
นี่คือชั้นวินัย ไม่ใช่ agent runtime หรือระบบ orchestration สำหรับรันงานข้ามคืน

## ดูการทำงานใน 15 วินาที

GIF นี้ขับด้วย hook ที่ ship จริง ไม่ใช่ mockup:

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/statusline-demo.gif" width="720" alt="แก้ไฟล์แล้วขึ้น unverified, verify แดงยังคงแดง และเปลี่ยนเป็นเขียวเมื่อผ่าน">
</p>

```text
✎ unverified   → มีการแก้หลังการตรวจครั้งล่าสุด
❌ verify RED  → การตรวจครั้งล่าสุดไม่ผ่าน
✅ verify 3m   → การตรวจผ่านเมื่อสามนาทีก่อน
```

## ป้องกันอะไร

| ความพัง | กลไกที่จับ |
|---|---|
| บอกว่า “เสร็จ” โดยไม่ตรวจ | Stop hook เตือน; strict gate แบบ opt-in บล็อกเมื่อผลแดง |
| นับ `cat test.sh` ว่ารัน test | จับคู่ `LUCIAZERO_VERIFY_CMD` แบบ exact |
| ลดความเข้ม test เพื่อให้เขียว | Doctrine ข้อ 3 + check-suppression guard |
| Test ใหม่ผ่านแม้ไม่มี fix | `revert-probe.sh` รัน test กับโค้ดเก่า |
| ทำ scope หายเงียบ ๆ | `/done` บังคับให้ส่งครบหรือระบุสิ่งที่เว้นไว้ |
| เดินเข้าทางตันเดิมอีกรอบ | `/retro` บันทึก และ `/debug` อ่านก่อนเริ่ม |
| Context หายตอนเปลี่ยน agent | `/lucia-relay` ส่งหลักฐาน next action และ negative knowledge |

กลไกที่ตรวจด้วยเครื่องรันใน `test.sh`; ข้ออ้างด้านพฤติกรรมวัดด้วย
[eval harness](eval/README.md)

## ส่งงานที่ยังไม่เสร็จข้าม agent

`/lucia-relay` ส่งต่อการตัดสินใจและหลักฐาน แทนการเท transcript ทั้งแชต
Session A สร้าง `LUCIA_RELAY.json` ที่เป็น canonical พร้อม human view
ที่ generate จากไฟล์นั้น ส่วน Session B ตรวจ Git fingerprint, อ่าน next action
กับสมมติฐานที่ถูกหักล้าง, รัน verification ซ้ำ แล้ว consume relay อย่างชัดเจน

Relay ต้องตัดสินก่อนว่าผู้รับอยู่ที่ไหน: ถ้าอยู่เครื่องเดิมใช้ full local path
ได้ แต่ถ้าข้ามเครื่องต้องเป็น commit ที่ clean และ push แล้วเท่านั้น ตัวตรวจจะ
ปฏิเสธ path เฉพาะเครื่อง และให้ใส่ความรู้ที่อยู่นอก repo ลงใน JSON โดยตรง

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/relay-demo.gif" width="720" alt="Session หนึ่งสร้าง Lucia Relay อีก session ตรวจสอบ พบ repository drift รันหลักฐานซ้ำ และ consume relay">
</p>

GIF นี้รัน [implementation ที่ ship จริง](docs/assets/relay-demo.sh) ใน Git
repository ชั่วคราว Fixture `relay-transfer` ใน CI ให้ reference ที่สมบูรณ์
6/6 และปฏิเสธ handoff Markdown ทั่วไป (1/6) กับ relay ที่เนื้อหาครบแต่
fingerprint เก่า (5/6) ตัวเลขเหล่านี้เป็นการตรวจ protocol ด้วยเครื่อง
**ไม่ใช่ผล uplift ของโมเดล** อ่าน [วิธีวัดและข้อจำกัด](docs/benchmark.md#skill-protocol-evidence)

## ติดตั้ง

### Claude Code plugin — แนะนำ

ได้ doctrine, skill ทั้งหมด, reviewer และ hook ติดตาม verify:

```text
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

เริ่ม repo ด้วย `/luciazero:ready` ชื่อ skill แบบ plugin มี prefix
`/luciazero:` และไม่มี statusline เพราะ Claude Code plugin ตั้งค่านี้ไม่ได้

### เฉพาะ skill — agent ที่รองรับ

```bash
npx skills add ohm41321/luciazero
```

ช่องทางนี้ติดตั้งเฉพาะ skill 11 ตัว ไม่มี doctrine, reviewer หรือ hook

### Classic Claude Code และ Codex

```bash
npx luciazero                 # Claude Code
npx luciazero --with-hooks    # Claude Code + hook/statusline; ต้องมี Python 3.9+
npx luciazero codex           # Codex CLI

npx luciazero uninstall
npx luciazero uninstall-codex
```

ฝั่ง Claude Code ให้เลือก plugin หรือ classic อย่างใดอย่างหนึ่งเพื่อไม่ต่อ hook
ซ้ำ Classic มี `--status`; Codex ได้ doctrine และ skill แต่ไม่มี hook/statusline
เฉพาะ Claude Installer สำรองชื่อที่ชน และตอนถอนจะลบเฉพาะสำเนาที่ Luciazero
ยืนยันความเป็นเจ้าของได้

## อัปเดต

Luciazero จะไม่แก้ไฟล์ของ classic หรือ Codex อยู่เบื้องหลัง

```bash
npx luciazero@latest check-update   # อ่านอย่างเดียว ติดต่อ npm เฉพาะตอนนี้
npx luciazero@latest update         # อัปเดต classic/Codex ทุกชุดที่ตรวจพบ
```

`update` รักษาโหมดเดิมว่า Claude classic ใช้ hook หรือไม่ ซ่อมไฟล์ managed ที่
เก่า จะไม่เริ่มติดตั้งใหม่ถ้าหา installation เดิมไม่พบ และจะหยุดเมื่อพบเวอร์ชัน
ที่ใหม่กว่าหรือข้อมูลเวอร์ชันเสีย หลังอัปเดตให้เริ่ม agent session ใหม่

ช่องทางอื่นใช้ตัวอัปเดตของช่องทางนั้น:

```bash
claude plugin update luciazero@luciazero   # แล้วรัน /reload-plugins
npx skills update                          # ตรวจ scope ใน prompt ก่อนยืนยัน
```

คำสั่ง skills จะอัปเดต skill ทุกตัวใน scope ที่เลือก ไม่ใช่เฉพาะ Luciazero
จึงควรตรวจ prompt ก่อนยืนยัน

Claude Code อัปเดต plugin ตอนเริ่มโปรแกรมอัตโนมัติได้: เปิด `/plugin` →
**Marketplaces** → **luciazero** → **Enable auto-update** โดย marketplace
ภายนอกจะปิดตัวเลือกนี้เป็นค่าเริ่มต้น ถ้าต้องการเพียงการแจ้งเตือน release ให้ใช้
GitHub **Watch → Custom → Releases**

## Skill ทั้ง 11 ตัว

รัน `/ready` ก่อนหนึ่งครั้ง ที่เหลือใช้เมื่อถึงจังหวะของมัน

| จังหวะ | Skill | ผลลัพธ์ |
|---|---|---|
| เข้า repository | `/ready` | หาหรือสร้างคำสั่ง verify และพิสูจน์ว่าแดงได้ |
| โครงสร้างหรือหลักฐานไล่อ่านยาก | `/show` | แสดงความเชื่อมโยง สิ่งที่เปลี่ยน และหลักฐานด้วยภาพที่เล็กที่สุด |
| อยากได้เสียงพูดแบบลูเซียระหว่างเขียนโค้ด | `/imouto-mode focus` | เพิ่มน้ำเสียงน้องสาวซึนเดเระแบบอ่อน ๆ; ต้องเปิดเองและค่าเริ่มต้นปิด |
| ก่อนงานเสี่ยง กำกวม หรือแตะหลาย module | `/plan` | ล็อก scope และหลักฐานยอมรับที่สังเกตได้ |
| บั๊กที่มองรอบแรกไม่ออก | `/debug` | Reproduction, hypothesis ledger, regression test |
| รู้ revision ดีและเสีย | `/bisect` | หา first bad commit ใน worktree ชั่วคราว |
| ก่อนบอกว่าเสร็จ | `/done` | Full verify, skeptic review และรายงาน scope |
| ต้องส่งงานไปที่อื่น | `/lucia-relay` | State แบบ JSON + Markdown พร้อมตรวจ drift |
| ปรับ performance | `/experiment` | Baseline, เกณฑ์ชนะ และการวัดแบบควบคุม |
| ดูนิสัยการ verify ในเครื่อง | `/discipline-report` | รายงาน outcome กรองตามเวลา/โปรเจกต์ |
| หลังงานยาก | `/retro` | เก็บบทเรียนและแนวทางที่พิสูจน์แล้วว่าไม่เวิร์ก |

`/imouto-mode` จะไม่เปิดตัวเอง ใช้ `focus` (แนะนำ), `on` หรือ `off` โดยโหมดมีผล
เฉพาะ invocation นั้น ไม่เขียน config และหลักฐานทางเทคนิคจะใช้ภาษาตรงเสมอ
ผู้ใช้ plugin เรียก `/luciazero:imouto-mode focus`; ผู้ใช้ Codex เรียก
`$imouto-mode focus`

Diff เสี่ยงจะผ่าน `reviewer` แบบอ่านอย่างเดียวใน focus `security`, `contract`
หรือ `general` ถ้าเสี่ยงทั้ง security และ contract จะตรวจแยกสองรอบ

## หลักฐาน

<!-- BEGIN GENERATED: benchmark-evidence -->

### ผล Claude

Snapshot: 2026-08-11 อัตราผ่านทุกเกณฑ์ สร้างจาก raw rows ที่ commit ไว้:

| โมเดล Claude | Luciazero | Bare | ผลต่าง |
|---|---:|---:|---:|
| Haiku†, 10 valid/task | 36/60 (60%) | 27/60 (45%) | +15pp |
| Sonnet, 4–5 valid/task* | 25/27 (93%) | 16/26 (62%) | +31pp |

Arm `Luciazero` ติดตั้ง classic pack แบบไม่มี hook จึงไม่ใช่การแยกผลของ
doctrine เพียงอย่างเดียว *Sonnet ยังเป็นผล preliminary เพราะ invalid 8 rows
ทำให้หลาย arm มี valid run เพียง 4 รอบ ส่วนผล top-up `+37pp` เดิมถูกยกเลิก
เพราะหา replacement raw rows ที่ใช้ตรวจสอบซ้ำไม่ได้

†Provenance ของโมเดล Haiku ยังไม่สมบูรณ์: มีเพียง 70/140 rows ที่บันทึก
model identity ส่วนอีก 70 rows ระบุได้แค่ระดับไฟล์/รายงานของ campaign
จึงตรวจสอบโมเดลซ้ำแบบราย row ไม่ได้

### GPT/Codex pilot — ผลสำรวจเบื้องต้น

Snapshot: 2026-08-12.

| โมเดล | invocation ที่ valid | task ที่จับคู่ได้ | Luciazero | Bare | ผลต่างที่พบ |
|---|---:|---:|---:|---:|---:|
| GPT-5.6 Terra, medium | 11/12* | 5 | 5/5 runs, 28/28 criteria | 5/5 runs, 28/28 criteria | +0pp† |

*Luciazero 1 run ถูกตัดเป็น invalid เพราะ model capacity เต็ม †นี่คือ
**สัญญาณว่า benchmark อาจง่ายเกินไป ไม่ใช่หลักฐานว่ามีหรือไม่มี uplift** เพราะ
pilot มีเพียง 1 run ต่อ arm ต่อ task ดู [ผลเต็ม](docs/benchmark.md),
[campaign registry](eval/results/campaigns.json) และ
[raw pilot](eval/results/gpt-5.6-terra-medium-pilot-2026-08-12.jsonl)

<!-- END GENERATED: benchmark-evidence -->

## Requirement และความปลอดภัย

- Node.js 18+ สำหรับ CLI และ discipline report
- Bash สำหรับ classic installer; Python 3.9+ สำหรับ hook และ Lucia Relay (`install.sh --with-hooks` ปฏิเสธเวอร์ชันเก่ากว่านี้)
- Installer, hook, helper และ grader หลักรัน offline ส่วน behavioral eval จริง
  เรียก model CLI และใช้เครดิต API หรือโควตา subscription
- Hook รันคำสั่งบนเครื่อง ควรอ่านก่อนเปิดใช้
- Telemetry ของ hook อยู่ใน private state แยกตาม session ภายในเครื่อง เก็บเวลา
  wall time ของ turn/Bash และจำนวน Bash, verify, skill ที่ model/user เรียก
  โดยไม่เก็บ command, ชื่อ skill หรือ path ดิบ
- ตั้ง `LUCIAZERO_VERIFY_CMD` เป็นคำสั่ง verify ระดับเร็วที่ exact ของ repo
- ใส่ `LUCIAZERO_STRICT_VERIFY_CMD` ใน personal settings เท่านั้น ห้าม commit ลง
  config ของ repository; strict mode จะ fail open เมื่อเกิด internal error
- `.claude/settings.json` ที่ commit ไว้ใน repository ตั้งค่า Luciazero ไม่ได้เลย:
  คีย์ `LUCIAZERO_*` ทุกตัว (รวม `CLAUDE_CONFIG_DIR`) ที่ประกาศไว้ที่นั่น — ทั้งใน
  ไดเรกทอรีที่เปิด session และไดเรกทอรีแม่จนถึง root ของ repo — จะถูกปฏิเสธ
  และแจ้งชื่อคีย์หนึ่งครั้งตอน `SessionStart` ส่วน settings ของคุณเองยังใช้ได้:
  การค้นหยุดที่ root ของ repo และที่ `$HOME` ไม่เคยอ่าน `~/.claude/settings.json`
  หรือ `.claude/settings.local.json` ของคุณ
- Windows: installer และ hook เป็นสคริปต์ Bash ให้รันใน WSL;
  `npx luciazero discipline` ใช้ได้บน Node ปกติ

อ่าน trust boundary ฉบับเต็มใน [SECURITY.md](SECURITY.md)

## พัฒนา repo นี้

```bash
./test.sh --fast   # loop ระหว่างทำ: ตรวจ doctrine/hook/report/Relay ส่วนหลัก
./test.sh          # ปิดงาน/CI: ตรวจ eval, packaging และ install แบบเต็ม
```

fast tier เป็นคำสั่งระหว่างทำงานของ repo นี้; ถ้าแก้ส่วนที่ fast tier ไม่ครอบคลุม
ให้ใช้คำสั่ง targeted ของส่วนนั้น ส่วน full tier (`./test.sh` หรือ
`./test.sh --full`) ครอบคลุม script, state ของ hook, Relay, bisect, manifest ของ
plugin/npm, eval grader ที่พิสูจน์ตัวเองได้ และ install → reinstall → uninstall
แบบ sandbox ทั้ง Claude Code และ Codex โดย CI และ `/done` ใช้ full tier

อ่านต่อ:

- [สถาปัตยกรรมและ trade-off](docs/comparison.md)
- [วิธีทำ eval](eval/README.md)
- [ผล benchmark และแผน GPT](docs/benchmark.md)
- [ทะเบียน raw campaign](eval/results/campaigns.json)
- [บันทึกการทดลอง](docs/experiments.md)
- [การ contribute](CONTRIBUTING.md)
- [การ publish](docs/publishing.md)
- [Changelog](CHANGELOG.md)

## ผลิตภัณฑ์ในเครือและสนับสนุน

Luciazero ใช้มาสคอตร่วมกับ [Lucia](https://lucia-discord-bot.vercel.app)
Discord bot ภาษาไทย ถ้า Luciazero ช่วยลดรอบ review ได้
[สนับสนุนโปรเจกต์ได้ที่นี่](https://easydonate.app/itsathitz) 💚

## License

[MIT](LICENSE)
