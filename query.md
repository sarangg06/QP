High-level strategy (fast + clean)

You want controlled combinatorics, not free-form generation.

Target

~150–250 SQL skeletons

20–40 NL variants per skeleton

= 7,000–9,000 pairs

Step 1: Extract your schema (1–2 hours)

Export:

Table names

Column names

Primary / foreign keys

Business meanings (comments if available)

Create a schema dictionary:

{
  "employees": {
    "columns": ["emp_id", "name", "dept_id", "salary", "status"],
    "meaning": "All full-time employees"
  },
  "departments": {
    "columns": ["dept_id", "dept_name"],
    "meaning": "Organizational departments"
  }
}


This becomes ground truth.

Step 2: Design SQL skeletons (MOST IMPORTANT) (1–2 days)

These are parameterized SQL templates.

Example skeleton
SELECT d.dept_name, AVG(e.salary) AS avg_salary
FROM employees e
JOIN departments d ON e.dept_id = d.dept_id
WHERE e.status = '{STATUS}'
GROUP BY d.dept_name;


Variables:

{STATUS} → active, inactive, terminated

How many skeletons do you need?
SQL Type	Skeletons
Simple SELECT	30–40
JOINs	60–80
GROUP BY	40–60
Subqueries / CTE	20–30
Edge cases	10–20

🎯 Total: ~180–220 skeletons

Step 3: Auto-expand skeletons into SQL (SCRIPTED) (½ day)

Use Python — not an LLM — for this.

from itertools import product

statuses = ["active", "inactive", "terminated"]
years = [2022, 2023, 2024]

queries = []

for s, y in product(statuses, years):
    queries.append(
        f"""
        SELECT d.dept_name, AVG(e.salary)
        FROM employees e
        JOIN departments d ON e.dept_id = d.dept_id
        WHERE e.status = '{s}' AND e.year = {y}
        GROUP BY d.dept_name;
        """
    )


This gives you:

Correct SQL

Guaranteed coverage

Zero hallucination

Step 4: Generate NL variants using an LLM (FAST) (½–1 day)

Now let the LLM do what it’s good at: language variation.

Prompt example:

Given this SQL query:

<SQL>

Generate 10 DISTINCT natural language questions
that a business user would ask.

Rules:
- Do NOT mention SQL
- Use organizational language
- Vary phrasing, tone, and abstraction


Each SQL → 10–20 NL queries.

Output structure
{
  "question": "Which departments have the highest average pay?",
  "sql": "SELECT d.dept_name..."
}

Step 5: Deduplicate aggressively (AUTOMATED) (½ day)

This step matters more than you think.

Use embeddings similarity:

SentenceTransformers

Cosine similarity threshold: 0.90–0.95

Remove near-duplicates:

“highest paid”

“top salary”

“maximum compensation”

Keep semantic diversity.

Step 6: Human review (targeted, not exhaustive) (1–2 days)

Do NOT review everything.

Instead:

Random sample 10%

Mandatory review:

Long queries

Subqueries

Joins >3 tables

Business-critical tables

Typical yield:

2–5% fixes

Huge quality improvement

Step 7: Inject “hard” examples (manual) (½ day)

Add ~300–500 intentionally tricky queries:

Ambiguous wording

Implicit joins

Business shorthand

Example:

"Who’s costing us the most this quarter?"


These teach the model organizational semantics.

Time & Effort Summary
Step	Time
Schema prep	1–2 hrs
SQL skeletons	1–2 days
Auto expansion	½ day
NL generation	½–1 day
Deduplication	½ day
Review	1–2 days

🕒 Total: ~5–7 working days

Why this is the MOST efficient way

✅ No hallucinated SQL
✅ Humans focus only where it matters
✅ Perfect label alignment
✅ Scales linearly
✅ Audit-friendly

Most teams that “just prompt GPT” end up throwing away 40–60% of the data.

One advanced trick (optional but powerful)

Train in curriculum order:

Simple SELECT

JOIN

GROUP BY

Subqueries

It stabilizes LoRA training and converges faster.

Final recommendation

If you want 7–9k queries fast and clean:

Design ~200 SQL skeletons → expand → LLM for language → dedupe → review

That’s the highest ROI path I know.
