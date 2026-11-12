<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@f10ec1e360be25bed98f48e50dd582fba986e20c/docs/assets/readme-banner-dark.svg">
    <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@f10ec1e360be25bed98f48e50dd582fba986e20c/docs/assets/readme-banner-light.svg" width="100%" alt="Luciazero: ให้ coding agent พิสูจน์งานก่อนบอกว่าเสร็จ ลูเซีย มาสคอตของโปรเจกต์ ยืนข้างเทอร์มินัลที่ agent บอกว่าเทสต์ผ่านหมด ./test.sh ออกด้วย exit 1 แก้พร้อม regression test แล้ว ./test.sh ออกด้วย exit 0 จากนั้น /done รัน full verify แล้วตามด้วย revert probe ที่แสดงว่าเทสต์ใหม่ไม่ผ่านถ้าไม่มี fix">
  </picture>
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/luciazero"><img src="https://img.shields.io/npm/v/luciazero" alt="npm version"></a>
  <a href="https://www.npmjs.com/package/luciazero"><img src="https://img.shields.io/npm/dw/luciazero" alt="npm weekly downloads"></a>
  <a href="https://github.com/ohm41321/luciazero/actions/workflows/ci.yml"><img src="https://github.com/ohm41321/luciazero/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <a href="https://github.com/ohm41321/luciazero/stargazers"><img src="https://img.shields.io/github/stars/ohm41321/luciazero?style=flat" alt="GitHub stars"></a>
  <a href="https://github.com/ohm41321/luciazero/network/members"><img src="https://img.shields.io/github/forks/ohm41321/luciazero?style=flat" alt="GitHub forks"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/ohm41321/luciazero" alt="MIT license"></a>
</p>

<div align="center">

[English](README.md) · **ภาษาไทย** · [เว็บไซต์](https://ohm41321.github.io/luciazero/th/) · [วิดีโอแนะนำสองนาที](https://ohm41321.github.io/luciazero/th/#intro)

</div>

<p align="center">
  <a href="#เริ่มใช้ใน-30-วินาที">เริ่มใช้</a> ·
  <a href="#ปกป้องอะไร">ปกป้องอะไร</a> ·
  <a href="#ดูลูปการทำงาน">ลูป</a> ·
  <a href="#ภาพรวม-skill-ทั้ง-13-ตัว">Skill</a> ·
  <a href="#ส่งต่องานข้าม-agent">Relay</a> ·
  <a href="#ให้-agent-สองตัวส่งงานหากัน">Agent Bus</a> ·
  <a href="#ติดตั้ง">ติดตั้ง</a> ·
  <a href="#หลักฐานและข้อจำกัด">หลักฐาน</a> ·
  <a href="#ความปลอดภัยและ-requirement">ความปลอดภัย</a>
</p>

---

Luciazero เป็นชั้น verification และ handoff สำหรับ **Claude Code, Codex CLI
และ runtime ที่ใช้ skill ได้** เหมาะกับทีมที่อยากให้ coding agent
พิสูจน์งานก่อนบอกว่าเสร็จ นี่คือชั้นวินัย ไม่ใช่ agent runtime

> งานเสร็จต้องพิสูจน์ด้วยคำสั่ง ไม่ใช่คำตัดสินของ agent
> ถ้ายังไม่มีคำสั่งตรวจ นั่นคือบั๊กแรก

| งาน | ทำอย่างไร |
|---|---|
| **พิสูจน์** | Stop hook เตือนเมื่อ agent จะหยุดทั้งที่มีการแก้หลังการตรวจครั้งล่าสุด หรือการตรวจนั้นแดง; strict gate แบบ opt-in บล็อกเมื่อผลแดง `/done` รัน full verify และ skeptic diff pass เพิ่ม revert probe เมื่อมีการแก้ test และ review อิสระหนึ่งรอบเมื่อ diff เสี่ยง |
| **รักษา&nbsp;scope** | `/done` บังคับให้ส่งครบทุกข้อหรือระบุสิ่งที่เว้นไว้ scope ที่หลุดจึงถูกบอกออกมาแทนที่จะหายเงียบ ๆ |
| **จำบทเรียน** | `/retro` บันทึกทางตันและกับดัก `/debug` อ่านก่อนลองรอบถัดไป |
| **ส่งต่องาน** | `/lucia-relay` ส่งหลักฐาน next action และ negative knowledge ไปยัง session, agent หรือเครื่องอื่น |

<p align="center">
  <strong>13 skills</strong> · <strong>Relay fixture 6/6</strong> · <strong>Claude + Codex</strong> · <strong>MIT</strong>
</p>
<p align="center"><sub>Relay 6/6 เป็นการตรวจ protocol ด้วยเครื่อง ส่วนผลด้านพฤติกรรมรายงานแยกต่างหาก</sub></p>

**checkout นี้คือ tree ของ 3.1.0** manifest กับรายการบนสุดใน
[changelog](CHANGELOG.md) ตรงกัน และเอกสารนี้อธิบาย source นั้น

- 3.1.0: `LUCIAZERO_VERIFY_CMD` ใส่ได้บรรทัดละหนึ่งคำสั่ง และนับ verify ที่รัน
  หลัง `cd`, wrapper หรือ assignment จึงใส่ได้ทั้ง tier เร็วและ tier เต็ม
  strict verify ที่ timeout จะบอกว่า timeout ส่วนใน Agent Bus beta
  (เฉพาะ checkout) `lucia stop` หยุด daemon ที่บันทึกไว้, state directory
  หนึ่งมี daemon ได้ตัวเดียว และ `service install` ไม่ติดตั้งข้าง daemon
  ที่ service ไม่ได้เปิดเอง
- 3.0.1 แก้ให้ stop nudge ไม่เงียบหลัง verify ที่ fail, นับไฟล์ที่แก้ผ่าน
  shell เป็นการแก้ไข, ให้ service บน Linux โหลดได้ และให้ Bash installer
  จัดการ CRLF ได้
- ตั้งแต่ 3.0.0 reviewer agent ชื่อ `lucia-reviewer`
  (ใน plugin คือ `luciazero:lucia-reviewer`) และ stop hook ตัดสินคำสั่งจาก
  โปรแกรมที่มันรันจริง type checker, linter และ check script ของ project นับ
  แต่การอ่านไฟล์ test ไม่นับ
- eval fixture ทั้ง 12 ชุดผ่าน offline ใน `./test.sh` แต่ยังไม่มี pilot
  skills-ablation กับ model จริง
- การรองรับ Windows แบบ native ซึ่งเพิ่มใน 2.7.0 ผ่าน CI บน `windows-latest`
  แล้ว แต่ยังไม่เคยรันบนเครื่อง Windows จริง
  [การทดสอบภาคสนามบน Windows](docs/windows-field-test.md) ระบุสิ่งที่ CI
  ไม่ครอบคลุม

## เริ่มใช้ใน 30 วินาที

เลือกช่องทางตาม agent ที่ใช้ แล้วเริ่ม session ใหม่

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
`$ready`) ช่องทางนี้ตั้งใจไม่ติดตั้ง doctrine, `lucia-reviewer` หรือ hook
ดูตารางเทียบทุกช่องทางที่[ติดตั้ง](#ติดตั้ง)

## ปกป้องอะไร

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@40d27aae08150e5fab87ca14af1cf7e8569cd0a1/docs/assets/film-false-green.gif" width="720" alt="agent ถูกสั่งให้แก้บั๊ก login แล้วตอบว่า Fixed. All tests pass. Done. เครื่องหมายถูกสีเขียวขึ้นว่ารันไป 0 ครั้ง วิดีโอถามว่า Actually tested? แล้วเครื่องหมายถูกก็แตก">
  <br><sub>ความพังข้อแรกในตาราง จาก<a href="https://ohm41321.github.io/luciazero/th/#intro">วิดีโอแนะนำ</a></sub>
</p>

| ความพัง | กลไกที่จับ |
|---|---|
| บอกว่า “เสร็จ” โดยไม่ตรวจ | Stop hook เตือน; strict gate แบบ opt-in บล็อกเมื่อผลแดง |
| นับ `cat test.sh` ว่ารัน test | ตรวจจากโปรแกรมที่คำสั่งรันจริง; ตั้ง `LUCIAZERO_VERIFY_CMD` แบบ exact ได้ |
| ลดความเข้ม test เพื่อให้เขียว | Doctrine ข้อ 3 + review ใน `/done`; มีตัวอย่าง hook กัน suppression แบบ opt-in |
| Test ใหม่ผ่านแม้ไม่มี fix | `revert-probe.cjs` รัน test กับโค้ดเก่า |
| ทำ scope หายเงียบ ๆ | `/done` บังคับให้ส่งครบหรือระบุสิ่งที่เว้นไว้ |
| เดินเข้าทางตันเดิมอีกรอบ | `/retro` บันทึก และ `/debug` อ่านก่อนเริ่ม |
| Context หายตอนเปลี่ยน agent | `/lucia-relay` ส่งหลักฐาน next action และ negative knowledge |

กลไกที่ตรวจด้วยเครื่องรันใน `test.sh`; ข้ออ้างด้านพฤติกรรมวัดด้วย
[eval harness](eval/README.md)

## ดูลูปการทำงาน

วิดีโอแนะนำสองนาที (แอนิเมชัน ภาษาอังกฤษ): agent บอกว่าผ่านทั้งที่ไม่ได้รันอะไร
ลูปที่จับได้ `/bisect` การส่งงานต่อระหว่าง agent และ `/done` ที่พิสูจน์ว่าเทสต์จับบั๊กได้จริง
อัตราผ่านในวิดีโอเป็นผลของ Claude Sonnet กับ classic pack แบบไม่มี hook
ดู[หลักฐานและข้อจำกัด](#หลักฐานและข้อจำกัด)

https://github.com/user-attachments/assets/e18f6092-12ae-4113-bfec-47765956bb49

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@40d27aae08150e5fab87ca14af1cf7e8569cd0a1/docs/assets/film-loop.gif" width="720" alt="ลูป: plan, change, verify ไม่ผ่านด้วย exit 1, fix แล้ว verify ผ่านด้วย exit 0 จากนั้นขึ้นข้อความ Done is proven by a command, not by my judgment">
  <br><sub>ลูปการทำงาน จาก<a href="https://ohm41321.github.io/luciazero/th/#intro">วิดีโอแนะนำ</a></sub>
</p>

ระหว่างทำงาน statusline บอกว่าลูปอยู่ตรงไหน:

```text
✎ unverified   → มีการแก้หลังการตรวจครั้งล่าสุด
❌ verify RED  → การตรวจครั้งล่าสุดไม่ผ่าน
✅ verify 3m   → การตรวจผ่านเมื่อสามนาทีก่อน
```

ดูมันเปลี่ยนบนเครื่องของคุณ ทั้งสอง script ใช้ directory ชั่วคราวและรัน
implementation จริง โดยไม่ใช้ model หรือ API

```bash
bash docs/assets/statusline-demo.sh   # hook driver กับ statusline ตัวจริง
bash docs/assets/relay-demo.sh        # การส่งต่องานข้าม session
```

## ภาพรวม skill ทั้ง 13 ตัว

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
| มีงานจาก agent อื่นรออยู่ในคิว (beta) | `/lucia-bus` | ลงทะเบียน อ่าน inbox claim ทำงาน และส่งผลผ่าน Agent Bus ในเครื่อง ([วิธีตั้งค่าและ demo](docs/agent-bus.md)) |
| อยากให้ agent สอง session คุยกัน (beta) | `/lucia-chat` | บอกว่าใครรออะไร เปิดหนึ่งหน้าต่างต่อ agent และเปิดหน้าต่างดูบทสนทนาได้ถ้าต้องการ |
| ปรับ performance | `/experiment` | Baseline, เกณฑ์ชนะ และการวัดแบบควบคุม |
| ดูนิสัยการ verify ในเครื่อง | `/discipline-report` | รายงาน outcome กรองตามเวลา/โปรเจกต์ |
| หลังงานยาก | `/retro` | เก็บบทเรียนและแนวทางที่พิสูจน์แล้วว่าไม่เวิร์ก |

`/imouto-mode` จะไม่เปิดตัวเอง ใช้ `focus` (แนะนำ), `on` หรือ `off` โดยโหมดมีผล
เฉพาะ invocation นั้น ไม่เขียน config และหลักฐานทางเทคนิคจะใช้ภาษาตรงเสมอ
ผู้ใช้ plugin เรียก `/luciazero:imouto-mode focus`; ผู้ใช้ Codex เรียก
`$imouto-mode focus`

Diff เสี่ยงจะผ่าน `lucia-reviewer` แบบอ่านอย่างเดียวใน focus `security`, `contract`
หรือ `general` ถ้าเสี่ยงทั้ง security และ contract จะตรวจรอบเดียวโดยระบุทั้งสอง
focus ไม่ใช่รอบละ focus diff เล็กที่ไม่เข้า route ใดไม่ต้อง review

ไฟล์คำสั่งของ agent โตขึ้นเรื่อย ๆ [context-weight](https://github.com/ohm41321/context-weight)
เป็น skill แยกจากผู้สร้างคนเดียวกัน ใช้วัดว่า `CLAUDE.md`, `AGENTS.md` และรายการ
skill กิน context เท่าไรก่อนเริ่มงาน แล้วช่วยตัดให้เล็กลงพร้อมพิสูจน์ว่าไม่มีบรรทัดไหนหาย

## ส่งต่องานข้าม agent

`/lucia-relay` ส่งต่อการตัดสินใจและหลักฐาน แทนการเท transcript ทั้งแชต
Session A สร้าง `LUCIA_RELAY.json` ที่เป็น canonical พร้อม human view
ส่วน Session B ตรวจ repository identity, HEAD และ manifest digest จากช่องทางที่เชื่อถือได้
อ่าน next action และ negative knowledge รัน verification ที่อนุมัติแล้วซ้ำ
ใน coding harness ของเครื่องรับ แล้วจึง consume อย่างชัดเจน

ทั้งหมดเหลือสองคำสั่งต่อฝั่ง:

```bash
# ฝั่งส่ง (session A)
luciazero relay draft --write     # เพิ่ม --recipient cross-machine --base <base> เมื่อต้อง publish transfer tag
                                  # ...กรอก JSON แล้วรัน:
luciazero relay finalize          # validate และสร้าง human view; ถ้าเป็น cross-machine จะพิมพ์
                                  # trusted envelope ให้ด้วย (--envelope-out <file> บันทึกเป็นไฟล์)

# ฝั่งรับ (session B)
luciazero relay inspect --trusted-envelope <file>
                                  # ...รันหลักฐานซ้ำให้ครบ แล้วจึง:
luciazero relay consume --verified --trusted-envelope <file>
```

เครื่องเดิมยังใช้ local path และ schema 1/2 ได้ ส่วน cross-machine schema 3
สร้างหลัง commit/push เท่านั้น โดย publish transfer tag ที่ตั้งชื่อตาม commit
และบันทึก clone URL ที่ตัด credential แล้ว, head/base OID, committed changed files
และ inline knowledge
ฝั่งรับต้องระบุ route, trusted HEAD และ manifest digest เอง จึง downgrade validation ด้วย
artifact ปลอมไม่ได้ รองรับ detached checkout และ Relay ไม่ execute command
จาก artifact ผู้รับต้องรันเองให้ครบก่อนใช้ `consume --verified`
envelope เชื่อถือได้ต่อเมื่อมาจากช่องทางที่ยืนยันตัวตนแล้วและระบุ path จากนอก clone
อย่างชัดเจน ไฟล์ที่ส่งมาพร้อม artifact จะถูกปฏิเสธ

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@40d27aae08150e5fab87ca14af1cf7e8569cd0a1/docs/assets/film-relay.gif" width="720" alt="Lucia Relay มาถึง session ใหม่บนเครื่องใหม่ รันหลักฐานซ้ำแล้วได้ความล้มเหลวเดิมตามที่บันทึกไว้ หลังแก้ price() รันซ้ำผ่านด้วย exit 0">
  <br><sub>relay มาถึงปลายทาง จาก<a href="https://ohm41321.github.io/luciazero/th/#intro">วิดีโอแนะนำ</a></sub>
</p>

วิดีโอเป็นแอนิเมชัน [relay demo](docs/assets/relay-demo.sh) รัน implementation ที่ ship จริง
ใน Git repository ชั่วคราว Fixture `relay-transfer` ใน CI ให้ reference ที่สมบูรณ์
6/6 และปฏิเสธ handoff Markdown ทั่วไป (1/6) กับ relay ที่เนื้อหาครบแต่
fingerprint เก่า (5/6) ตัวเลขเหล่านี้เป็นการตรวจ protocol ด้วยเครื่อง
**ไม่ใช่ผล uplift ของโมเดล** อ่าน [วิธีวัดและข้อจำกัด](docs/benchmark.md#skill-protocol-evidence)

## ให้ agent สองตัวส่งงานหากัน

**Agent Bus เป็น beta แบบ opt-in และใช้ได้จาก checkout เท่านั้น** มันไม่ได้มา
กับ `npx luciazero` และจะไม่เริ่มทำงานระหว่างการติดตั้ง npm, plugin หรือ
skills-only ตามปกติ หลัง setup checkout ครั้งเดียว การใช้งานประจำเหลือคำสั่ง
เดียวในแต่ละหน้าต่าง:

```text
หน้าต่าง A                             หน้าต่าง B
$ lucia claude                       $ lucia codex

task_create + message_send  ───────► เก็บใน local bus แบบ durable
                             nudge ─► check your bus inbox (1 new task from claude)
                                      message_ack + task_claim
                                      ทำงาน + verify
                                      artifact_publish + task_complete
ผลอยู่ใน inbox               ◄─────── message_send
```

daemon เริ่มเมื่อ session แรกที่เปิดผ่าน `lucia` ต้องใช้ แต่ละ CLI ได้ MCP
configuration เฉพาะ run นั้น จึงไม่แก้ config กลางของ Claude หรือ Codex
ข้อความและสถานะ task อยู่ใน SQLite บนเครื่อง และข้อความของ peer จะไม่ถูกพิมพ์
เข้า prompt ของอีก session ตัว proxy พิมพ์เฉพาะ inbox notice ที่ daemon
ประกอบเอง หลัง provider เงียบแล้ว

ลอง demo ที่ ship มาด้วย fake provider ได้โดยไม่ใช้ model, login หรือ quota:

```bash
bash docs/assets/agent-bus-demo.sh
```

ถ้าจะเปิด Claude Code กับ Codex จริง ให้ทำ
[checkout setup ครั้งเดียว](docs/agent-bus.md#start-here) ก่อน แล้วรัน
`lucia claude` กับ `lucia codex` อ่าน [คู่มือ Agent Bus](docs/agent-bus.md)
สำหรับ ownership ของ worktree, `--no-nudge`, ขอบเขตความปลอดภัย และการล้างข้อมูล

ภายใน workflow ของ Bus skill จะหยุดก่อนงานเสี่ยง: delete, deploy, การเข้าถึง
production, การใช้เงิน, force-push, การเปลี่ยน public contract และการขยาย scope
ต้องใช้ nonce ครั้งเดียวที่คุณสร้างเองในเทอร์มินัลของคุณ ไม่มี bus tool ใดสร้างให้ได้
และ nonce ที่ถูกใส่ลงใน message, task หรือ artifact จะถูกลบหรือปฏิเสธ
([approvals](docs/agent-bus.md#approvals)) สิ่งนี้บันทึกที่มาของการอนุมัติ
ไม่ใช่ sandbox ของเครื่องที่กันโปรเซสอื่นซึ่งรันในชื่อคุณ ส่วน trust boundary
ของโปรเจกต์อยู่ใน [SECURITY.md](SECURITY.md)

## ติดตั้ง

Luciazero รองรับ Claude Code, Codex CLI และ agent ที่ใช้ skill ได้ แต่ละช่องทาง
ได้ส่วนของ pack ไม่เท่ากัน:

| ช่องทาง | Doctrine | skill ทั้ง 13 ตัว | `lucia-reviewer` | Hook + statusline |
|---|:---:|:---:|:---:|:---:|
| Claude Code plugin | ✓ | ✓ | ✓ | เฉพาะ hook |
| Classic, Claude Code | ✓ | ✓ | ✓ | เมื่อใช้ `--with-hooks` |
| Classic, Codex CLI | ✓ | ✓ | ✓ (เป็น skill) | — |
| Codex CLI plugin | ✓ | ✓ | — | เฉพาะ hook |
| เฉพาะ skill | — | ✓ | — | — |

<details>
<summary><strong>แนะนำ · Claude Code plugin</strong></summary>

ได้ doctrine, skill ทั้งหมด, `lucia-reviewer` และ hook ติดตาม verify:

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

ช่องทางนี้ติดตั้งเฉพาะ skill 13 ตัว ไม่มี doctrine, `lucia-reviewer` หรือ hook

</details>

<details>
<summary><strong>Codex CLI plugin · doctrine, skill และ hook</strong></summary>

```bash
codex plugin marketplace add ohm41321/luciazero
codex plugin add luciazero@luciazero
```

ได้ doctrine, skill ทั้ง 13 ตัว และ hook ติดตาม verify แต่ไม่มี `lucia-reviewer`
หรือ statusline Codex บอก hook ว่าคำสั่งพิมพ์อะไรออกมา แต่ไม่บอกว่าผ่านหรือไม่
ใต้ Codex รอบ verify จึงนับว่ารันแล้ว ไม่เคยนับว่าเขียว ไม่มี nudge ตอนแดง และ
strict gate จะรันคำสั่งของมันตอน stop แทนการเชื่อรอบก่อนหน้า ให้เลือก plugin นี้
หรือ `npx luciazero codex` อย่างใดอย่างหนึ่ง เพราะทั้งคู่จะโหลด skill ซ้ำ อัปเดตด้วย
`codex plugin marketplace upgrade luciazero` ถอนด้วย
`codex plugin remove luciazero@luciazero` Codex ยัง refresh Git marketplace
เองด้วย จึงควรเริ่ม session ของ Codex ที่เปิดค้างไว้ใหม่หลังอัปเดต

</details>

<details>
<summary><strong>Classic install · Claude Code หรือ Codex CLI</strong></summary>

ติดตั้งคำสั่งแบบ global ครั้งเดียวโดยไม่ใช้ `sudo`:

```bash
npx luciazero@latest global-install
```

คำสั่งนี้ติดตั้ง CLI ไว้ใต้ `~/.local/npm` และหลังผู้ใช้ยืนยันจะเพิ่มไดเรกทอรี
bin เข้า PATH ของ zsh หรือ bash เปิด shell ใหม่แล้วเรียกคำสั่ง global ได้จากทุก
ไดเรกทอรี:

```bash
luciazero                 # Claude Code
luciazero --with-hooks    # Claude Code + hook/statusline; ต้องมี Node 18+
luciazero codex           # Codex CLI

luciazero uninstall             # ถอน classic files ฝั่ง Claude
luciazero uninstall-codex       # ถอน classic files ฝั่ง Codex
luciazero global-status         # ตรวจคำสั่ง global และ PATH
luciazero global-uninstall      # ถอนคำสั่งและ PATH block ที่เป็นของ Luciazero
```

ถ้าต้องการรันครั้งเดียวโดยไม่เก็บคำสั่งไว้ ใช้ `npx luciazero@latest` ได้เหมือน
เดิม งาน automation ส่ง `global-install --yes` ได้ ส่วนการใช้แบบโต้ตอบจะถาม
ก่อนติดตั้งแพ็กเกจหรือเปลี่ยนไฟล์เริ่มต้นของ shell
บน Windows `global-install` ใช้ global prefix ของ npm เอง
(`%APPDATA%\npm` ถ้าไม่ได้ย้าย) และไม่แก้ไฟล์เริ่มต้นใดหรือ Path ทั้ง
`global-install` และ `global-status` จะแจ้งถ้า prefix นั้นไม่อยู่ใน Path

ฝั่ง Claude Code ให้เลือก plugin หรือ classic อย่างใดอย่างหนึ่ง เพราะติดตั้งทั้งคู่
จะโหลด skill และ `lucia-reviewer` ซ้ำ แม้ hook กับ doctrine จะ dedupe ได้
Classic มี `--status`; Codex แบบ classic ได้ doctrine และ skill แต่ไม่มี hook
(Codex plugin มี hook) Installer สำรองชื่อที่ชน และตอนถอนจะลบเฉพาะสำเนาที่ Luciazero
ยืนยันความเป็นเจ้าของได้

</details>

## อัปเดตอย่างปลอดภัย

Luciazero จะไม่แก้ไฟล์ของ classic หรือ Codex อยู่เบื้องหลัง แต่ละช่องทางใช้ตัว
อัปเดตของตัวเอง:

| ติดตั้งด้วย | อัปเดตด้วย |
|---|---|
| Classic หรือ Codex | `luciazero update` (`luciazero check-update` อ่านอย่างเดียว) |
| Claude Code plugin | `claude plugin update luciazero@luciazero` แล้วรัน `/reload-plugins` |
| Codex CLI plugin | `codex plugin marketplace upgrade luciazero` แล้วเริ่ม session ใหม่ |
| เฉพาะ skill | `npx skills update` หรือ `npx skills update done -g` สำหรับ skill เดียว |

```bash
luciazero check-update   # อ่านอย่างเดียว ติดต่อ npm เฉพาะตอนนี้
luciazero update         # อัปเดต classic/Codex ทุกชุดที่ตรวจพบ
```

ถ้าเลือกเส้นทางแบบรันครั้งเดียว ให้เรียกสองคำสั่งเดียวกันผ่าน
`npx luciazero@latest` แทน

`update` รักษาโหมดเดิมว่า Claude classic ใช้ hook หรือไม่ ซ่อมไฟล์ managed ที่
เก่า จะไม่เริ่มติดตั้งใหม่ถ้าหา installation เดิมไม่พบ และจะหยุดเมื่อพบเวอร์ชัน
ที่ใหม่กว่าหรือข้อมูลเวอร์ชันเสีย หลังอัปเดตให้เริ่ม agent session ใหม่

คำสั่ง skills จะอัปเดต skill ทุกตัวใน scope ที่เลือก ไม่ใช่เฉพาะ Luciazero
จึงควรตรวจ prompt ก่อนยืนยัน ถ้าต้องการอัปเดตเพียงตัวเดียวให้ใช้รูปแบบ targeted

Claude Code อัปเดต plugin ตอนเริ่มโปรแกรมอัตโนมัติได้: เปิด `/plugin` →
**Marketplaces** → **luciazero** → **Enable auto-update** โดย marketplace
ภายนอกจะปิดตัวเลือกนี้เป็นค่าเริ่มต้น ถ้าต้องการเพียงการแจ้งเตือน release ให้ใช้
GitHub **Watch → Custom → Releases**

## หลักฐานและข้อจำกัด

ผลด้านล่างเป็นการวัดเบื้องต้นและขึ้นกับโมเดลกับ task โดยตรง ให้ยึด raw rows
และวิธีวัดที่ลิงก์ไว้เป็นหลัก ไม่ใช่คำรับประกันว่าจะ uplift กับทุก repository
หรือทุกโมเดล

<!-- BEGIN GENERATED: benchmark-evidence -->

### ผล Claude

Snapshot: 2026-08-11 สำหรับ Haiku และ Sonnet pilot, 2026-09-02 สำหรับ Sonnet
อัตราผ่านทุกเกณฑ์ สร้างจาก raw rows ที่ commit ไว้:

| โมเดล Claude | จำนวน task | Luciazero | Bare | ผลต่าง | ต้นทุนต่อ run | เวลาต่อ run |
|---|---:|---:|---:|---:|---:|---:|
| Haiku†, 10 valid/task | 6 | 36/60 (60%) | 27/60 (45%) | +15pp | $0.08 vs $0.07 | 54 s vs 48 s |
| Sonnet (2026-08-11 pilot), 4–5 valid/task* | 6 | 25/27 (93%) | 16/26 (62%) | +31pp | $0.21 vs $0.18 | 38 s vs 33 s |
| Sonnet, 5 valid/task | 10 | 39/50 (78%) | 23/50 (46%) | +32pp | $0.39 vs $0.22 | 93 s vs 47 s |

Arm `Luciazero` ติดตั้ง classic pack แบบไม่มี hook จึงไม่ใช่การแยกผลของ
doctrine เพียงอย่างเดียว และแต่ละแถวเทียบข้ามกันตรงๆ ไม่ได้ เพราะ campaign
Sonnet วันที่ 2026-09-02 เพิ่ม task ที่ยากขึ้นอีก 4 ตัวซึ่ง campaign วันที่
2026-08-11 ไม่เคยรัน ให้เทียบแต่ละแถวกับ arm bare ของตัวเองเท่านั้น
*Sonnet pilot ยังเป็นผล preliminary เพราะ invalid 8 rows ทำให้หลาย arm มี
valid run เพียง 4 รอบ campaign วันที่ 2026-09-02 มาแทนที่ด้วย valid run
ครบ 5 รอบทุก cell และไม่มี invalid เลย ส่วนผล top-up `+37pp` เดิมยังถูกยกเลิก
เพราะหา replacement raw rows ที่ใช้ตรวจสอบซ้ำไม่ได้

ส่วนต่างส่วนใหญ่ของ Sonnet มาจาก 2 task: `merge-conflict` กับ `pipeline` ให้ 10
จาก 16 run ที่ผ่านเพิ่มขึ้น และไม่ได้คำนวณช่วงความไม่แน่นอน
จึงควรอ่านส่วนต่างเป็นทิศทางมากกว่าขนาด ส่วนต่างส่วนใหญ่มาจากการทิ้ง regression
test ไว้: ถ้านับทุกเกณฑ์ยกเว้น 3 เกณฑ์ที่ขอ test ซึ่งล้มเมื่อไม่มี fix
(`regression-red`, `regression-test`, `tests-bite`) สอง arm ผ่าน 40/50 กับ 36/50
doctrine ข้อ 4 ขอ test นั้น ผลที่วัดได้จึงอยู่ที่การทิ้ง test ไว้มากกว่าการแก้
bug ได้มากขึ้น `relay-transfer` ตรวจตาม format relay ของ Luciazero เอง
(`LUCIA_RELAY.json`) ซึ่ง prompt ไม่ได้บอก จึงได้เปรียบฝั่ง Luciazero ถ้าตัด
task นี้ออก ส่วนต่างของ Sonnet เป็น +31pp ต้นทุนต่อ run คือค่าเฉลี่ยราคา API ที่
CLI รายงาน เวลาต่อ run คือค่าเฉลี่ยเวลาจริง (median ของ Sonnet: 45 s กับ 40 s)

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

| ต้องมี | ใช้กับ |
|---|---|
| Node.js 18+ | CLI, discipline report, hook และ status line รวมถึง helper ที่ `/ready`, `/done` และ `/bisect` เรียก (`node <skill-dir>/scripts/*.cjs`; ชื่อ `.sh` เดิมเป็น wrapper ที่ต้องใช้ Node เช่นกัน) |
| Bash | classic installer บน macOS และ Linux |
| Claude Code 2.1.139+ | hook ซึ่งต่อแบบ exec form (`install.sh --with-hooks` ปฏิเสธ Node ที่เก่ากว่า 18) |
| Python 3.9+ | Lucia Relay: `python3 <skill-dir>/scripts/relay.py` หรือ `python` / `py -3` บน Windows |
| Python 3.10+ และ checkout | Agent Bus daemon (beta, opt-in) |

Agent Bus daemon ไม่อยู่ใน npm payload และ `npx luciazero` ไม่เคยเริ่ม daemon
จาก checkout ให้รัน `./install.sh` (บน Windows ใช้ `node bin\luciazero.js`)
เพื่อติดตั้ง launcher `luciazero-agentd` และ `lucia` ไว้ที่ `~/.claude/bin`
(`LUCIAZERO_BIN_DIR` เลือกไดเรกทอรีอื่นได้ และการรันครั้งต่อไปจะจำไว้) แล้ว
`luciazero-agentd service install` จะรัน daemon ผ่าน launchd, systemd `--user`
หรือ Task Scheduler บน Windows ดู [docs/agent-bus.md](docs/agent-bus.md)

- Installer, hook, helper และ grader หลักรัน offline ส่วน behavioral eval จริง
  เรียก model CLI และใช้เครดิต API หรือโควตา subscription
- Hook รันคำสั่งบนเครื่อง ควรอ่านก่อนเปิดใช้
- Telemetry ของ hook อยู่ใน private state แยกตาม session ภายในเครื่อง เก็บเวลา
  wall time ของ turn/Bash/verify, จำนวน green ซ้ำโดยไม่มี edit คั่น และจำนวน
  Bash, verify, skill ที่ model/user เรียก แต่ละแถวของสถิติระบุ project ด้วย hash
  และชื่อโฟลเดอร์ไว้ใช้ใน report โดยไม่เก็บ command, ชื่อ skill หรือ path ดิบ
  ข้อมูลเก่าที่ไม่มีเวลา verify จะแสดงว่ายังไม่ได้วัด ไม่ใช่ศูนย์
- ใส่ `LUCIAZERO_STRICT_VERIFY_CMD` ใน personal settings เท่านั้น ห้าม commit ลง
  config ของ repository; strict mode จะ fail open เมื่อเกิด internal error มันรัน
  ตอน stop เว้นแต่คำสั่งเดียวกันนั้นเขียวอยู่แล้วหลัง edit ล่าสุด โดยรันได้นานสุด
  `LUCIAZERO_STRICT_TIMEOUT` วินาที (ค่าเริ่มต้น 120) รอบที่ timeout ไม่ตัดสินอะไร
  และ nudge จะบอกว่ามัน timeout
- `.claude/settings.json` ที่ commit ไว้ใน repository ตั้งค่า Luciazero ไม่ได้เลย:
  คีย์ `LUCIAZERO_*` ทุกตัว (รวม `CLAUDE_CONFIG_DIR`) ที่ประกาศไว้ที่นั่น — ทั้งใน
  ไดเรกทอรีที่เปิด session และไดเรกทอรีแม่จนถึง root ของ repo — จะถูกปฏิเสธ
  และแจ้งชื่อคีย์หนึ่งครั้งตอน `SessionStart` ส่วน `.claude/settings.local.json`
  ที่ git track อยู่ก็ถูกปฏิเสธแบบเดียวกัน settings ของคุณเองยังใช้ได้:
  การค้นหยุดที่ root ของ repo และที่ `$HOME` ไม่เคยอ่าน `~/.claude/settings.json`
  หรือ `.claude/settings.local.json` ที่ไม่ได้ track
- Windows รันได้โดยตรงโดยไม่ต้องใช้ WSL (ผ่าน CI เท่านั้น; ดูต้นหน้านี้):
  `npx luciazero` ติดตั้งผ่าน installer ที่ port เป็น Node, `global-install`
  ใช้ global prefix ของ npm เอง และ hook,
  status line และ skill helper เป็น Node ทั้งหมด บน Windows โปรแกรมที่
  Luciazero เรียกด้วยชื่อ — git, node, npm, Python, provider CLI, PowerShell,
  schtasks — ค้นจาก PATH เท่านั้น ไม่ค้นใน working directory ซึ่ง Windows
  จะค้นก่อน

<details>
<summary><strong>hook นับอะไรเป็น verify</strong></summary>

- โดย default hook นับคำสั่งเป็น verify จากโปรแกรมที่มันรันจริง ได้แก่
  test runner (`pytest`, `npm test`, `node --test`, `go test`, `./test.sh`),
  type checker (`tsc`, `mypy`), linter (`eslint`, `ruff check`, `shellcheck`)
  และ check script ของ project (`npm run check`,
  `python scripts/check-site.py`) การอ่านไฟล์ test ไม่นับ การรันโปรแกรมด้วย
  `--help` หรือ `--version` อย่างเดียวก็ไม่นับ การแก้ไฟล์ใน temporary directory
  ที่อยู่นอก project และไม่อยู่ใน git work tree เช่น scratchpad ของ agent
  ไม่ปลุก nudge
- ไฟล์ที่คำสั่ง shell แก้ (`sed -i`, heredoc, formatter, commit hook) นับเป็น edit
  ด้วย ก่อน verify แต่ละรอบและตอน stop hook ถาม git ว่าไฟล์ไหนเปลี่ยนระหว่างที่คำสั่ง
  shell ของ session นั้นรันอยู่ หลัง verify ครั้งล่าสุดจบ ไม่นับเอกสาร ไฟล์ที่ ignore
  สิ่งที่ verify เขียนเอง และ edit ของ session อื่นที่เกิดระหว่างสองคำสั่ง คำสั่งที่
  test ก่อนแล้วค่อยแก้ (`npm test && sed -i ...`) ถือว่า edit นั้นยังไม่ได้ verify
  ถ้าอยู่นอก git work tree จะไม่ตามการเขียนผ่าน shell
- ถ้า verify ล่าสุดของ edit ใน session นั้นล้ม หรือหาคำสั่งไม่เจอ stop จะถูกเตือน
  หนึ่งครั้งเช่นกัน จนกว่าจะมีรอบที่ผ่าน เฉพาะ Claude Code: Codex ส่ง output ของคำสั่ง
  ให้ hook แต่ไม่บอกว่าผ่านหรือไม่
- ถ้าต้องการนับเฉพาะคำสั่ง verify ของ repo เอง ให้ตั้ง `LUCIAZERO_VERIFY_CMD` ใน
  personal settings บรรทัดละหนึ่งคำสั่ง (`./test.sh --fast` และ `./test.sh`)
  คำสั่งจะนับเมื่อมันรันหนึ่งในนั้น รวมถึงเมื่อมี `cd`, wrapper อย่าง `timeout`
  หรือการตั้งตัวแปรนำหน้า ใส่ระดับ full ไว้ด้วย ไม่อย่างนั้นรอบ closeout ที่ `/done`
  ขอจะโดน nudge
- knob อื่นที่อ่านจาก personal settings เท่านั้น: `LUCIAZERO_VERIFY_REGEX` แทนการตรวจ
  แบบ default ด้วย extended regex ที่ลองกับแต่ละบรรทัดของคำสั่ง;
  `LUCIAZERO_DOC_REGEX` (ค่าเริ่มต้น `\.(md|markdown|rst)$`) ระบุไฟล์ที่เป็นเอกสาร
  ซึ่งแก้แล้วไม่ต้อง verify; `LUCIAZERO_RELAY_STALE_DAYS` (ค่าเริ่มต้น 7) คือจำนวนวัน
  ที่ `LUCIA_RELAY.json` จะถูกเรียกว่าเก่าตอนเริ่ม session
- `LUCIAZERO_EDIT_DIAG=1` ใน shell ของคุณเอง ทำให้ hook เก็บหนึ่งบรรทัดต่อ edit event
  ไว้ใน state directory ของมัน (ชื่อ tool, key แบบ opaque, `file_path` ขาด/ว่าง/มีค่า,
  นามสกุล, อยู่ใต้ cwd หรือไม่, นับเป็น edit หรือไม่ — ไม่เก็บ path หรือเนื้อหา)
  ไว้หาว่าอะไร re-arm nudge ทั้งที่ไม่เห็น edit

</details>

อ่าน trust boundary ฉบับเต็มใน [SECURITY.md](SECURITY.md)

## พัฒนา Luciazero

```bash
./test.sh --discipline  # แก้ hook, report หรือ skill prompt: ราว 30 วินาที
./test.sh --fast        # loop ระหว่างทำ: เพิ่ม Relay, bisect, evidence
./test.sh --bus         # แก้ agentd/ หรือ script ของ Bus: daemon suite กับ gate ที่ใช้ fake provider
./test.sh               # ปิดงาน/CI: ตรวจ eval, packaging และ install แบบเต็ม
LZ_TEST_TIMINGS=1 ./test.sh --fast   # เพิ่มบรรทัด `TIMING gate=<name> seconds=<n>` ต่อ gate ทาง stderr
scripts/test-timings.sh --fast       # รันแบบเดียวกัน และเก็บ stdout/stderr/meta ไว้ใต้ .test-timings/
scripts/test-timings.sh --report     # median กับ p95 ต่อ gate จาก sample สีเขียวที่เก็บไว้
                                     # พร้อม commit ที่ sample มาจาก (เตือนเมื่อปนมากกว่าหนึ่ง revision)
```

discipline tier เป็นคำสั่ง loop สำหรับ enforcement pack, discipline report และ
prompt: syntax และ ShellCheck ของทุก script ที่ ship (และ parse ด้วย bash 3.2
เมื่อ `LZ_BASH32` ชี้ไปที่ bash 3.2; CI รันเสมอ), contract ของ prompt/doctrine
และ state machine ของ hook เท่านั้น fast tier เป็นคำสั่งระหว่างทำงาน
ของส่วนอื่น; ถ้าแก้ส่วนที่ fast tier ไม่ครอบคลุมให้ใช้คำสั่ง targeted ของส่วนนั้น ส่วน full tier (`./test.sh` หรือ
`./test.sh --full`) ครอบคลุม script, state ของ hook, Relay, bisect, manifest ของ
plugin/npm, eval grader ที่พิสูจน์ตัวเองได้ และ install → reinstall → uninstall
แบบ sandbox ทั้ง Claude Code และ Codex โดย CI และ `/done` ใช้ full tier
`test.sh` เป็นตัว dispatch ส่วนตัวตรวจอยู่ใน `tests/gates/*.sh` แยกไฟล์ตาม
subsystem และถูก source ตามลำดับ อ่านเฉพาะ gate ที่งานแตะ ใน full tier gate
tiers, eval, packaging, install, codex-install และ parity รันพร้อมกันคนละ subshell แล้ว
replay output ตามลำดับเดิมจึงอ่านเหมือนรันเรียง; `LZ_TEST_PARALLEL=0` รันทีละ gate

อ่านต่อ:

- [สถาปัตยกรรมและ trade-off](docs/comparison.md)
- [วิธีทำ eval](eval/README.md)
- [ผล benchmark และแผน GPT](docs/benchmark.md)
- [ทะเบียน raw campaign](eval/results/campaigns.json)
- [บันทึกการทดลอง](docs/experiments.md)
- [Launch kit](docs/launch-kit.md)
- [การ contribute](CONTRIBUTING.md)
- [การ publish](docs/publishing.md)
- [Changelog](CHANGELOG.md)

## สนับสนุนโปรเจกต์

Luciazero ใช้มาสคอตร่วมกับ [Lucia](https://lucia-discord-bot.vercel.app)
Discord bot ภาษาไทย ถ้า Luciazero ช่วยลดรอบ review ได้
[สนับสนุนโปรเจกต์ได้ที่นี่](https://easydonate.app/itsathitz) 💚

## License

[MIT](LICENSE)
