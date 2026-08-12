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
9 ตัว, hook ติดตามการ verify, reviewer ที่ route ตามความเสี่ยง และ eval harness
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

## ติดตั้ง

> badge npm แสดง package ที่ publish ล่าสุด จนกว่าจะ tag และ publish `2.0.0`
> คำสั่ง `npx luciazero` ยังติดตั้ง npm release รุ่นเก่า ส่วนช่องทาง GitHub/plugin
> ใช้ source ปัจจุบันของ repository นี้

### Claude Code plugin — แนะนำ

ได้ doctrine, skill ทั้งหมด, reviewer และ hook ติดตาม verify:

```text
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

เริ่ม repo ด้วย `/luciazero:luciazero-bootstrap` ชื่อ skill แบบ plugin มี prefix
`/luciazero:` และไม่มี statusline เพราะ Claude Code plugin ตั้งค่านี้ไม่ได้

### เฉพาะ skill — agent ที่รองรับ

```bash
npx skills add ohm41321/luciazero
```

ช่องทางนี้ติดตั้งเฉพาะ skill 9 ตัว ไม่มี doctrine, reviewer หรือ hook

### Classic Claude Code และ Codex

```bash
npx luciazero                 # Claude Code
npx luciazero --with-hooks    # Claude Code + hook/statusline; ต้องมี Python 3
npx luciazero codex           # Codex CLI

npx luciazero uninstall
npx luciazero uninstall-codex
```

ฝั่ง Claude Code ให้เลือก plugin หรือ classic อย่างใดอย่างหนึ่งเพื่อไม่ต่อ hook
ซ้ำ Classic มี `--status`; Codex ได้ doctrine และ skill แต่ไม่มี hook/statusline
เฉพาะ Claude Installer สำรองชื่อที่ชน และตอนถอนจะลบเฉพาะสำเนาที่ Luciazero
ยืนยันความเป็นเจ้าของได้

## Skill ทั้ง 9 ตัว

รัน `/luciazero-bootstrap` ก่อนหนึ่งครั้ง ที่เหลือใช้เมื่อถึงจังหวะของมัน

| จังหวะ | Skill | ผลลัพธ์ |
|---|---|---|
| เข้า repository | `/luciazero-bootstrap` | หาหรือสร้างคำสั่ง verify และพิสูจน์ว่าแดงได้ |
| ก่อนงานเสี่ยงหรือหลายขั้น | `/plan` | ล็อก scope และหลักฐานยอมรับที่สังเกตได้ |
| บั๊กที่มองรอบแรกไม่ออก | `/debug` | Reproduction, hypothesis ledger, regression test |
| รู้ revision ดีและเสีย | `/bisect` | หา first bad commit ใน worktree ชั่วคราว |
| ก่อนบอกว่าเสร็จ | `/done` | Full verify, skeptic review และรายงาน scope |
| ต้องส่งงานไปที่อื่น | `/lucia-relay` | State แบบ JSON + Markdown พร้อมตรวจ drift |
| ปรับ performance | `/experiment` | Baseline, เกณฑ์ชนะ และการวัดแบบควบคุม |
| ดูนิสัยการ verify ในเครื่อง | `/discipline-report` | รายงาน outcome กรองตามเวลา/โปรเจกต์ |
| หลังงานยาก | `/retro` | เก็บบทเรียนและแนวทางที่พิสูจน์แล้วว่าไม่เวิร์ก |

Diff เสี่ยงจะผ่าน `reviewer` แบบอ่านอย่างเดียวใน focus `security`, `contract`
หรือ `general` ถ้าเสี่ยงทั้ง security และ contract จะตรวจแยกสองรอบ

## หลักฐาน

### ผล Claude ที่เผยแพร่

Snapshot: 2026-08-11 อัตราผ่านครบทุกเกณฑ์:

| Claude model | Luciazero | Bare | ผลต่าง |
|---|---:|---:|---:|
| Haiku, valid 10/task | 36/60 (60%) | 27/60 (45%) | +15pp |
| Sonnet, valid 4–5/task* | 25/27 (93%) | 16/26 (62%) | +31pp |

Arm `Luciazero` ติดตั้ง classic pack แบบไม่มี hook จึงไม่ใช่การแยกผลของ doctrine
เพียงอย่างเดียว *ผล Sonnet ยังต่ำกว่าเกณฑ์เผยแพร่ที่ต้องมี valid run อย่างน้อย 5
ครั้งต่อ arm

### GPT/Codex pilot — ผลสำรวจเบื้องต้น

Snapshot: 2026-08-12

| Model | Valid invocation | Task ที่จับคู่ได้ | Luciazero | Bare | ผลต่างที่พบ |
|---|---:|---:|---:|---:|---:|
| GPT-5.6 Terra, medium | 11/12* | 5 | 5/5 run, 28/28 criteria | 5/5 run, 28/28 criteria | 0pp† |

*Luciazero 1 run ถูกตัดเป็น invalid เพราะ model capacity เต็ม †นี่คือ
**สัญญาณว่า benchmark อาจง่ายเกินไป ไม่ใช่หลักฐานว่ามีหรือไม่มี uplift** เพราะ
pilot มีเพียง 1 run ต่อ arm ต่อ task ดู [ผลเต็ม](docs/benchmark.md) และ
[ข้อมูล pilot ดิบ](eval/results/gpt-5.6-terra-medium-pilot-2026-08-12.jsonl)

## Requirement และความปลอดภัย

- Node.js 18+ สำหรับ CLI และ discipline report
- Bash สำหรับ classic installer; Python 3 สำหรับ hook และ Lucia Relay
- Installer, hook, helper และ grader หลักรัน offline ส่วน behavioral eval จริง
  เรียก model CLI และใช้เครดิต API หรือโควตา subscription
- Hook รันคำสั่งบนเครื่อง ควรอ่านก่อนเปิดใช้
- ตั้ง `LUCIAZERO_VERIFY_CMD` เป็นคำสั่ง verify ระดับเร็วที่ exact ของ repo
- ใส่ `LUCIAZERO_STRICT_VERIFY_CMD` ใน personal settings เท่านั้น ห้าม commit ลง
  config ของ repository; strict mode จะ fail open เมื่อเกิด internal error

อ่าน trust boundary ฉบับเต็มใน [SECURITY.md](SECURITY.md)

## พัฒนา repo นี้

```bash
./test.sh
```

ชุดทดสอบครอบคลุม script, state ของ hook, Relay, bisect, manifest ของ plugin/npm,
eval grader ที่พิสูจน์ตัวเองได้ และ install → reinstall → uninstall แบบ sandbox
ทั้ง Claude Code และ Codex

อ่านต่อ:

- [สถาปัตยกรรมและ trade-off](docs/comparison.md)
- [วิธีทำ eval](eval/README.md)
- [ผล benchmark และแผน GPT](docs/benchmark.md)
- [การ contribute](CONTRIBUTING.md)
- [การ publish](docs/publishing.md)
- [Changelog](CHANGELOG.md)

## ผลิตภัณฑ์ในเครือและสนับสนุน

Luciazero ใช้มาสคอตร่วมกับ [Lucia](https://lucia-discord-bot.vercel.app)
Discord bot ภาษาไทย ถ้า Luciazero ช่วยลดรอบ review ได้
[สนับสนุนโปรเจกต์ได้ที่นี่](https://easydonate.app/itsathitz) 💚

## License

[MIT](LICENSE)
