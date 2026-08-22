<div align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@37cb470e2b7c704ff32f3a46dbb125e312875960/docs/assets/lucia.png" width="220" alt="Lucia — มาสคอตของ Luciazero">
  <h1>Luciazero</h1>
  <p>
    <strong>ชั้นวินัยที่พิสูจน์ได้ด้วยหลักฐานสำหรับ coding agent</strong><br>
    <code>วางแผน → แก้ → ตรวจ → แก้ซ้ำ</code>
  </p>
  <p>
    <a href="https://www.npmjs.com/package/luciazero"><img src="https://img.shields.io/npm/v/luciazero" alt="npm version"></a>
    <a href="https://github.com/ohm41321/luciazero/actions/workflows/ci.yml"><img src="https://github.com/ohm41321/luciazero/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
    <a href="LICENSE"><img src="https://img.shields.io/github/license/ohm41321/luciazero" alt="MIT license"></a>
  </p>
</div>

[English](README.md) · **ภาษาไทย**

Luciazero เป็นชั้นวินัยขนาดเล็กสำหรับ coding agent รองรับ Claude Code,
Codex CLI และ runtime ที่ใช้ skill ได้ ผ่านการติดตั้งแบบ plugin, CLI
หรือเฉพาะ skill

> งานเสร็จต้องพิสูจน์ด้วยคำสั่ง ไม่ใช่คำตัดสินของ agent
> ถ้ายังไม่มีคำสั่งตรวจ นั่นคือบั๊กแรก

Luciazero เหมาะกับทีมที่อยากให้ coding agent พิสูจน์งานก่อนบอกว่าเสร็จ
ช่วยป้องกันการ verify แบบ false-green และ scope ที่หาย เก็บบทเรียนจากทางตันเดิม
และส่ง context ข้าม handoff ได้เมื่อใช้ `/lucia-relay` นี่คือชั้นวินัย ไม่ใช่ agent runtime

## เริ่มใช้ใน 30 วินาที

เลือกช่องทางตาม agent ที่ใช้ แล้วเริ่ม session ใหม่:

**Claude Code · full pack**

```text
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

ใน session ใหม่รัน `/luciazero:ready`

**Codex CLI · doctrine + skill**

```bash
npx luciazero codex
```

ใน session ใหม่รัน `$ready`

**เฉพาะ skill · agent ที่รองรับ**

```bash
npx skills add ohm41321/luciazero
```

เรียกใช้ skill `ready` ด้วย syntax ของ agent ที่ใช้ (ถ้าเป็น Codex CLI ให้ใช้
`$ready`) ช่องทางนี้ตั้งใจไม่ติดตั้ง doctrine, reviewer หรือ hook

## ดูลูปการทำงาน

GIF นี้ขับด้วย hook ที่ ship จริง ไม่ใช่ mockup:

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@37cb470e2b7c704ff32f3a46dbb125e312875960/docs/assets/statusline-demo.gif" width="720" alt="แก้ไฟล์แล้วขึ้น unverified, verify แดงยังคงแดง และเปลี่ยนเป็นเขียวเมื่อผ่าน">
</p>

```text
✎ unverified   → มีการแก้หลังการตรวจครั้งล่าสุด
❌ verify RED  → การตรวจครั้งล่าสุดไม่ผ่าน
✅ verify 3m   → การตรวจผ่านเมื่อสามนาทีก่อน
```

## ปกป้องอะไร

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

## ส่งต่องานข้าม agent

`/lucia-relay` ส่งต่อการตัดสินใจและหลักฐาน แทนการเท transcript ทั้งแชต
Session A สร้าง `LUCIA_RELAY.json` ที่เป็น canonical พร้อม human view
ส่วน Session B ตรวจ repository identity, HEAD และ manifest digest จากช่องทางที่เชื่อถือได้
อ่าน next action และ negative knowledge รัน verification ที่อนุมัติแล้วซ้ำ
ใน coding harness ของเครื่องรับ แล้วจึง consume อย่างชัดเจน

เครื่องเดิมยังใช้ local path และ schema 1/2 ได้ ส่วน cross-machine schema 3
สร้างหลัง commit/push เท่านั้น โดย publish transfer tag ที่ตั้งชื่อตาม commit
และบันทึก clone URL ที่ตัด credential แล้ว, head/base OID, committed changed files
และ inline knowledge
ฝั่งรับต้องระบุ route, trusted HEAD และ manifest digest เอง จึง downgrade validation ด้วย
artifact ปลอมไม่ได้ รองรับ detached checkout และ Relay ไม่ execute command
จาก artifact ผู้รับต้องรันเองให้ครบก่อนใช้ `consume --verified`

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@37cb470e2b7c704ff32f3a46dbb125e312875960/docs/assets/relay-demo.gif" width="720" alt="Session หนึ่งสร้าง Lucia Relay อีก session ตรวจสอบ พบ repository drift รันหลักฐานซ้ำ และ consume relay">
</p>

GIF นี้รัน [implementation ที่ ship จริง](docs/assets/relay-demo.sh) ใน Git
repository ชั่วคราว Fixture `relay-transfer` ใน CI ให้ reference ที่สมบูรณ์
6/6 และปฏิเสธ handoff Markdown ทั่วไป (1/6) กับ relay ที่เนื้อหาครบแต่
fingerprint เก่า (5/6) ตัวเลขเหล่านี้เป็นการตรวจ protocol ด้วยเครื่อง
**ไม่ใช่ผล uplift ของโมเดล** อ่าน [วิธีวัดและข้อจำกัด](docs/benchmark.md#skill-protocol-evidence)

## ติดตั้ง

Luciazero รองรับ Claude Code, Codex CLI และ agent ที่ใช้ skill ได้ เลือกช่องทาง
ที่เหมาะกับ workflow ของคุณ

<details>
<summary><strong>แนะนำ · Claude Code plugin</strong></summary>

ได้ doctrine, skill ทั้งหมด, reviewer และ hook ติดตาม verify:

```text
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

เริ่ม repo ด้วย `/luciazero:ready` ชื่อ skill แบบ plugin มี prefix
`/luciazero:` และไม่มี statusline เพราะ Claude Code plugin ตั้งค่านี้ไม่ได้

</details>

<details>
<summary><strong>เฉพาะ skill · agent ที่รองรับ</strong></summary>

```bash
npx skills add ohm41321/luciazero
```

ช่องทางนี้ติดตั้งเฉพาะ skill 11 ตัว ไม่มี doctrine, reviewer หรือ hook

</details>

<details>
<summary><strong>Classic install · Claude Code หรือ Codex CLI</strong></summary>

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

</details>

## อัปเดตอย่างปลอดภัย

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
npx skills update                          # ทุก skill ใน scope ที่เลือก
npx skills update done -g                 # เฉพาะ skill "done" แบบ global
```

คำสั่ง skills จะอัปเดต skill ทุกตัวใน scope ที่เลือก ไม่ใช่เฉพาะ Luciazero
จึงควรตรวจ prompt ก่อนยืนยัน ถ้าต้องการอัปเดตเพียงตัวเดียวให้ใช้รูปแบบ targeted

Claude Code อัปเดต plugin ตอนเริ่มโปรแกรมอัตโนมัติได้: เปิด `/plugin` →
**Marketplaces** → **luciazero** → **Enable auto-update** โดย marketplace
ภายนอกจะปิดตัวเลือกนี้เป็นค่าเริ่มต้น ถ้าต้องการเพียงการแจ้งเตือน release ให้ใช้
GitHub **Watch → Custom → Releases**

## ภาพรวม skill ทั้ง 11 ตัว

เรียกใช้ `ready` ก่อนหนึ่งครั้ง (`/ready` สำหรับ agent ที่ใช้ slash และ `$ready`
ใน Codex) ที่เหลือใช้เมื่อถึงจังหวะของมัน

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

## หลักฐานและข้อจำกัด

ผลด้านล่างเป็นการวัดเบื้องต้นและขึ้นกับโมเดลกับ task โดยตรง ให้ยึด raw rows
และวิธีวัดที่ลิงก์ไว้เป็นหลัก ไม่ใช่คำรับประกันว่าจะ uplift กับทุก repository
หรือทุกโมเดล

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

## ความปลอดภัยและ requirement

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

## พัฒนา Luciazero

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

## สนับสนุนโปรเจกต์

Luciazero ใช้มาสคอตร่วมกับ [Lucia](https://lucia-discord-bot.vercel.app)
Discord bot ภาษาไทย ถ้า Luciazero ช่วยลดรอบ review ได้
[สนับสนุนโปรเจกต์ได้ที่นี่](https://easydonate.app/itsathitz) 💚

## License

[MIT](LICENSE)
