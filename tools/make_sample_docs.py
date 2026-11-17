"""Generate samples/policy_short.docx and samples/notes.txt (small demo documents)."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"

POLICY = [
    ("1. Purpose and Scope", [
        "This policy explains the leave entitlements available to employees of Brightwater Logistics Ltd and the rules for requesting, "
        "approving and recording leave. It applies to all permanent and fixed term employees, whether they work full time or part time. "
        "Contractors and agency staff are governed by the terms of their own agreements.",
        "The policy is intended to give employees a clear understanding of what they can expect and to give managers a consistent basis for "
        "decisions. Where national law grants a greater entitlement than this policy, the law prevails.",
    ]),
    ("2. Annual Leave", [
        "Every full time employee is entitled to 24 working days of paid annual leave in each leave year, in addition to public holidays. "
        "The leave year runs from 1 January to 31 December. Part time employees receive a pro rata entitlement based on their contracted hours.",
        "Employees must give at least 14 calendar days of notice for any period of annual leave of five working days or more. Shorter periods "
        "require three working days of notice. Managers will normally respond to a request within five working days.",
        "No more than 15 consecutive working days of annual leave may be taken at one time without the written approval of the department head. "
        "During the final two weeks of December the warehouse teams operate a reduced leave quota to protect peak season service.",
    ]),
    ("3. Carry Over of Unused Leave", [
        "Employees may carry over a maximum of 8 unused annual leave days into the following leave year. Carried over days must be used by "
        "31 March, after which they lapse without payment. The human resources office sends a reminder on 1 February each year.",
        "In exceptional circumstances, such as extended sickness absence that prevented leave from being taken, the Director of People may "
        "approve a longer carry over period. Requests must be made in writing before 15 January.",
    ]),
    ("4. Sick Leave", [
        "Employees who are unable to work because of illness must inform their line manager before the start of their normal working day, "
        "or as soon as practicable. A medical certificate is required after 3 consecutive working days of absence.",
        "Company sick pay is paid at full salary for the first 20 working days in any rolling twelve month period and at half salary for a "
        "further 40 working days. After that period, statutory sick pay applies. Managers will hold a return to work conversation after any "
        "absence of five working days or more.",
        "Employees who are absent for reasons related to a long term condition may ask for reasonable adjustments. These requests are handled "
        "in confidence by the human resources office with occupational health advice where needed.",
    ]),
    ("5. Parental Leave", [
        "Employees who have completed 12 months of service are entitled to 26 weeks of parental leave at full pay following the birth or "
        "adoption of a child. A further 26 weeks of unpaid leave is available on request. Both parents may take leave, and the leave may be "
        "taken in up to two separate blocks within the first 24 months.",
        "Employees should tell their manager about their intention to take parental leave at least 15 weeks before the expected date. The human "
        "resources office will confirm the dates and pay arrangements in writing within ten working days.",
        "Employees returning from parental leave are entitled to return to the same role or, if that is not reasonably practicable, to a "
        "suitable alternative role on no less favourable terms.",
    ]),
    ("6. Bereavement and Compassionate Leave", [
        "Employees are entitled to 5 working days of paid bereavement leave on the death of a spouse, partner, child, parent or sibling. "
        "For other close relatives, up to 2 working days of paid leave are available. Additional unpaid leave can be agreed with the line "
        "manager.",
        "Managers are asked to handle these requests with sensitivity and without requiring evidence at the time of the request.",
    ]),
    ("7. Study and Volunteering Leave", [
        "The company grants up to 6 days of paid study leave per leave year for approved professional qualifications. Study leave is approved "
        "by the department head and should be agreed at least four weeks in advance of examinations.",
        "Employees may also take 2 paid volunteering days each year to support a registered charity. Requests should include the name of the "
        "organisation and a brief description of the activity.",
    ]),
    ("8. Requesting and Recording Leave", [
        "All leave requests are made through the Brightwater self service portal. The portal routes each request to the employee's line manager "
        "and records the decision. Employees should not book non-refundable travel until approval has been confirmed.",
        "Managers must keep a team calendar so that cover is maintained. Where two employees request the same dates and cover cannot be "
        "provided for both, priority is given to the request received first, unless it concerns a family emergency.",
    ]),
    ("9. Leave on Termination of Employment", [
        "Employees who leave the company will be paid for any accrued but untaken annual leave, calculated on a pro rata basis for the leave "
        "year. Where an employee has taken more leave than they have accrued, the excess may be deducted from final pay in accordance with "
        "the law.",
    ]),
    ("10. Contacts and Review", [
        "Questions about this policy should be sent to the human resources office at the address shown on the staff intranet. The policy is "
        "owned by the Director of People, Marguerite Ostrander, and was last reviewed on 12 September 2033. The next review is due in "
        "September 2035.",
    ]),
]

TABLE = [
    ("Leave type", "Entitlement", "Notice required"),
    ("Annual leave", "24 working days per year", "14 days for 5 days or more"),
    ("Carry over", "8 days, use by 31 March", "Automatic"),
    ("Sick leave", "20 days full pay, 40 days half pay", "Before start of shift"),
    ("Parental leave", "26 weeks full pay", "15 weeks before due date"),
    ("Bereavement", "5 days for close family", "As soon as practicable"),
    ("Study leave", "6 days per year", "4 weeks"),
    ("Volunteering", "2 days per year", "2 weeks"),
]

NOTES = """Lecture 4: Memory Hierarchy and Caching
Course: Computer Systems Fundamentals, Week 3

Why a hierarchy at all
Fast memory is small and expensive, large memory is slow and cheap. A hierarchy gives the illusion of a memory that is both large and fast
by keeping recently used data close to the processor. Typical access times: registers under 1 ns, L1 cache about 1 ns, L2 about 4 ns,
L3 about 15 ns, main memory about 80 ns, solid state disk about 100 microseconds.

Locality
Temporal locality: an item used recently is likely to be used again soon. Spatial locality: items near a recently used item are likely
to be used soon. Loops over arrays exhibit both. Caches exploit temporal locality by retaining lines and spatial locality by fetching
whole lines of 64 bytes.

Cache organisation
A direct mapped cache maps each block to exactly one line. A fully associative cache lets a block go anywhere. A set associative cache
is the compromise, with 4 way and 8 way designs being common. The index bits select the set, the tag bits identify the block.

Example worked in class
A 32 KB, 8 way cache with 64 byte lines has 512 lines and 64 sets. That means 6 index bits and 6 offset bits. On a 32 bit address
the tag has 20 bits.

Miss types (the three Cs)
Compulsory misses happen on the first touch. Capacity misses happen when the working set exceeds the cache. Conflict misses happen
when too many blocks map to the same set.

Write policies
Write through updates memory on every write. Write back marks the line dirty and writes it out on eviction. Most modern caches
use write back with write allocate.

Average memory access time
AMAT = hit time + miss rate x miss penalty. With a 1 ns hit time, a 5 percent miss rate and a 60 ns penalty the AMAT is 4 ns.

Reminders
Assignment 2 is due on Friday of week 5. The midterm covers lectures 1 to 5. Office hours are on Tuesdays at 14:00 in room B214.
"""


def build_docx(path: Path) -> None:
    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(12)
    st.paragraph_format.space_after = Pt(10)
    st.paragraph_format.line_spacing = 1.5
    d.add_heading("Brightwater Logistics Ltd", level=0)
    d.add_heading("Employee Leave Policy", level=1)
    d.add_paragraph("Policy reference HR-LV-07. Version 4.2. Effective from 1 October 2033. Owner: Director of People.")
    d.add_paragraph("This is a fictional policy created for software demonstration purposes.")
    d.add_page_break()
    half = len(POLICY) // 2
    for i, (head, paras) in enumerate(POLICY):
        if head[:2] in ("4.", "7."):
            d.add_page_break()
        d.add_heading(head, level=2)
        for p in paras:
            d.add_paragraph(p)
        if i == half:
            d.add_heading("Summary of Entitlements", level=2)
            t = d.add_table(rows=len(TABLE), cols=3)
            t.style = "Light Grid Accent 1"
            for r, row in enumerate(TABLE):
                for c, txt in enumerate(row):
                    t.cell(r, c).text = txt
            d.add_paragraph("")
    d.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build_docx(OUT / "policy_short.docx")
    (OUT / "notes.txt").write_text(NOTES, encoding="ascii")
    for n in ("policy_short.docx", "notes.txt"):
        print(n, (OUT / n).stat().st_size, "bytes")


if __name__ == "__main__":
    main()
