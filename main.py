#!/usr/bin/env python3
"""Personal Expense Tracker (standard library only, Python 3.8+).

Safety features:
  * Money uses Decimal (never float), so totals are always exact.
  * Every input is validated; bad input re-prompts instead of crashing.
  * Saves are atomic (temp file + replace), so a crash can't corrupt your data.
  * If expenses.json is damaged, a backup copy is made before anything is touched.
  * If a save fails, the in-memory change is rolled back.
  * Type 'cancel' (or press Ctrl+C) at any prompt to back out safely.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "expenses.json"
EXPORT_FILE = BASE_DIR / "expenses_export.csv"

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("1000000000")
SCHEMA_VERSION = 1
DEFAULT_CATEGORIES = [
    "Food", "Transport", "Housing", "Utilities", "Health",
    "Entertainment", "Shopping", "Education", "Savings", "Other",
]
CATEGORY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 &/'\-]{0,29}")


class Cancel(Exception):
    """Raised when the user backs out of a prompt."""


# --------------------------------------------------------------------------
# Parsing / validation
# --------------------------------------------------------------------------
def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def parse_amount(text: str) -> Decimal:
    cleaned = text.replace(",", "").replace("$", "").strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError("Enter a number like 12.50")
    if not value.is_finite():
        raise ValueError("Enter a valid number")
    if value <= 0:
        raise ValueError("Amount must be greater than 0")
    if value > MAX_AMOUNT:
        raise ValueError("Amount is too large")
    if value != value.quantize(CENT):
        raise ValueError("Use at most 2 decimal places")
    return value.quantize(CENT)


def parse_date(text: str, allow_future: bool = False) -> str:
    try:
        parsed = datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Use the format YYYY-MM-DD (e.g. 2026-11-25)")
    if parsed.year < 2000:
        raise ValueError("Year must be 2000 or later")
    if not allow_future and parsed > date.today():
        raise ValueError("Date cannot be in the future")
    return parsed.isoformat()


def parse_month(text: str) -> str:
    try:
        return datetime.strptime(text.strip(), "%Y-%m").strftime("%Y-%m")
    except ValueError:
        raise ValueError("Use the format YYYY-MM (e.g. 2026-11)")


def parse_description(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise ValueError("Description can't be empty")
    if len(text) > 100:
        raise ValueError("Keep it under 100 characters")
    if not text.isprintable():
        raise ValueError("Description contains invalid characters")
    return text


def parse_category(text: str, known: list) -> str:
    text = " ".join(text.split())
    if text.isdigit():
        n = int(text)
        if 1 <= n <= len(known):
            return known[n - 1]
        raise ValueError(f"Pick a number from 1 to {len(known)}, or type a new category")
    if not CATEGORY_RE.fullmatch(text):
        raise ValueError("Pick a number, or type a category (letters/numbers, max 30 chars)")
    for existing in known:
        if existing.lower() == text.lower():
            return existing
    return text[0].upper() + text[1:]


def parse_yes_no(text: str) -> bool:
    answer = text.strip().lower()
    if answer in ("y", "yes"):
        return True
    if answer in ("n", "no", ""):
        return False
    raise ValueError("Please answer y or n")


# --------------------------------------------------------------------------
# Input helpers
# --------------------------------------------------------------------------
def ask(prompt: str) -> str:
    try:
        text = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise Cancel
    if text.lower() == "cancel":
        raise Cancel
    return text


def prompt(label: str, parser, default=None):
    """Ask until the answer is valid. Empty input returns `default` if given."""
    while True:
        suffix = f" [{default}]" if default is not None else ""
        text = ask(f"{label}{suffix}: ")
        if text == "" and default is not None:
            return default
        try:
            return parser(text)
        except ValueError as exc:
            print(f"  ✗ {exc}")


def confirm(label: str) -> bool:
    return prompt(f"{label} (y/N)", parse_yes_no)


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
class Store:
    def __init__(self, path: Path):
        self.path = path
        self.expenses = []          # list of dicts; amount is Decimal
        self.budget = None          # monthly budget (Decimal) or None
        self._load()

    # ---- loading ----
    def _backup(self, reason: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.stem}.backup-{stamp}{self.path.suffix}")
        try:
            shutil.copy2(self.path, backup)
            print(f"⚠ {reason}. Original saved as {backup.name}")
        except OSError as exc:
            print(f"⚠ {reason}, and the backup failed ({exc}). Not saving to avoid data loss.")
            sys.exit(1)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"Cannot read {self.path.name}: {exc}")
            sys.exit(1)
        if not text.strip():
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._backup("expenses.json is not valid JSON; starting fresh")
            return

        if isinstance(data, list):
            raw_list, raw_budget = data, None
        elif isinstance(data, dict):
            raw_list, raw_budget = data.get("expenses", []), data.get("monthly_budget")
        else:
            self._backup("expenses.json has an unexpected format; starting fresh")
            return
        if not isinstance(raw_list, list):
            self._backup("expenses.json has an unexpected format; starting fresh")
            return

        bad = 0
        used_ids = set()
        for raw in raw_list:
            try:
                record = self._parse_record(raw)
            except (ValueError, KeyError, TypeError, InvalidOperation):
                bad += 1
                continue
            if record["id"] in used_ids:
                record["id"] = 0     # reassigned below
            else:
                used_ids.add(record["id"])
            self.expenses.append(record)
        next_id = max(used_ids, default=0) + 1
        for record in self.expenses:
            if record["id"] == 0:
                record["id"] = next_id
                next_id += 1
        if bad:
            self._backup(f"{bad} invalid entr{'y' if bad == 1 else 'ies'} skipped")
        if raw_budget is not None:
            try:
                self.budget = parse_amount(str(raw_budget))
            except ValueError:
                self.budget = None

    @staticmethod
    def _parse_record(raw: dict) -> dict:
        if not isinstance(raw, dict):
            raise TypeError("entry is not an object")
        raw_id = raw.get("id", 0)
        if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id < 0:
            raw_id = 0
        category = str(raw.get("category") or "Other")
        if not CATEGORY_RE.fullmatch(" ".join(category.split())):
            category = "Other"
        return {
            "id": raw_id,
            "date": parse_date(str(raw["date"]), allow_future=True),
            "amount": parse_amount(str(raw["amount"])),
            "category": " ".join(category.split()),
            "description": parse_description(str(raw.get("description") or "(no description)")),
        }

    # ---- saving ----
    def save(self) -> None:
        payload = {
            "version": SCHEMA_VERSION,
            "monthly_budget": str(self.budget) if self.budget is not None else None,
            "expenses": [
                {**e, "amount": str(e["amount"])} for e in self.expenses
            ],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    @contextmanager
    def transaction(self):
        """Apply changes, save, and roll back in memory if saving fails."""
        snapshot = ([dict(e) for e in self.expenses], self.budget)
        try:
            yield
            self.save()
        except BaseException:
            self.expenses, self.budget = snapshot
            raise

    # ---- helpers ----
    def next_id(self) -> int:
        return max((e["id"] for e in self.expenses), default=0) + 1

    def categories(self) -> list:
        extra = sorted({e["category"] for e in self.expenses} - set(DEFAULT_CATEGORIES))
        return DEFAULT_CATEGORIES + extra

    def find(self, expense_id: int):
        return next((e for e in self.expenses if e["id"] == expense_id), None)

    def month_total(self, month: str) -> Decimal:
        return sum((e["amount"] for e in self.expenses if e["date"][:7] == month), Decimal("0"))


# --------------------------------------------------------------------------
# Display
# --------------------------------------------------------------------------
def print_table(rows: list) -> None:
    print(f"\n{'ID':>4}  {'Date':<10}  {'Amount':>13}  {'Category':<15}  Description")
    print("-" * 70)
    for e in rows:
        print(f"{e['id']:>4}  {e['date']:<10}  {money(e['amount']):>13}  "
              f"{e['category'][:15]:<15}  {e['description'][:40]}")
    total = sum((e["amount"] for e in rows), Decimal("0"))
    print("-" * 70)
    print(f"{len(rows)} expense(s), total {money(total)}\n")


def budget_status(store: Store, month: str) -> None:
    if store.budget is None:
        return
    spent = store.month_total(month)
    left = store.budget - spent
    pct = spent / store.budget * 100
    print(f"Budget {month}: {money(spent)} of {money(store.budget)} ({pct:.0f}%)")
    if left < 0:
        print(f"  ⚠ Over budget by {money(-left)}")
    elif pct >= 80:
        print(f"  ⚠ Only {money(left)} left")
    else:
        print(f"  ✓ {money(left)} left")


def pick_expense(store: Store) -> dict:
    if not store.expenses:
        print("No expenses yet.")
        raise Cancel

    def parser(text: str) -> dict:
        if not text.isdigit():
            raise ValueError("Enter an expense ID (a number)")
        found = store.find(int(text))
        if found is None:
            raise ValueError("No expense with that ID")
        return found

    return prompt("Expense ID", parser)


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
def add_expense(store: Store) -> None:
    print("\nAdd expense (type 'cancel' to go back)")
    amount = prompt("Amount", parse_amount)
    when = prompt("Date (YYYY-MM-DD)", parse_date, default=date.today().isoformat())
    cats = store.categories()
    for i, name in enumerate(cats, 1):
        print(f"  {i:>2}. {name}")
    category = prompt("Category (number or new name)", lambda t: parse_category(t, cats))
    description = prompt("Description", parse_description)
    with store.transaction():
        store.expenses.append({
            "id": store.next_id(), "date": when, "amount": amount,
            "category": category, "description": description,
        })
    print(f"✓ Added {money(amount)} for {description} ({category})")
    budget_status(store, when[:7])


def list_expenses(store: Store) -> None:
    if not store.expenses:
        print("\nNo expenses yet.")
        return
    month = prompt("Month (YYYY-MM, blank for all)", lambda t: parse_month(t) if t else "", default="")
    rows = [e for e in store.expenses if not month or e["date"][:7] == month]
    if not rows:
        print("No expenses found.")
        return
    print_table(sorted(rows, key=lambda e: (e["date"], e["id"])))


def search_expenses(store: Store) -> None:
    term = prompt("Search for", lambda t: t.strip() or (_ for _ in ()).throw(ValueError("Enter something to search")))
    term = term.lower()
    rows = [e for e in store.expenses
            if term in e["description"].lower() or term in e["category"].lower()]
    if not rows:
        print("No matches.")
        return
    print_table(sorted(rows, key=lambda e: (e["date"], e["id"])))


def edit_expense(store: Store) -> None:
    expense = pick_expense(store)
    print_table([expense])
    print("Press Enter to keep the current value.")
    amount = prompt("Amount", parse_amount, default=expense["amount"])
    when = prompt("Date (YYYY-MM-DD)", parse_date, default=expense["date"])
    cats = store.categories()
    if expense["category"] not in cats:
        cats.append(expense["category"])
    category = prompt("Category (name or number)", lambda t: parse_category(t, cats),
                      default=expense["category"])
    description = prompt("Description", parse_description, default=expense["description"])
    with store.transaction():
        expense.update(amount=amount, date=when, category=category, description=description)
    print("✓ Updated")


def delete_expense(store: Store) -> None:
    expense = pick_expense(store)
    print_table([expense])
    if not confirm("Delete this expense permanently?"):
        print("Kept.")
        return
    with store.transaction():
        store.expenses.remove(expense)
    print("✓ Deleted")


def summary(store: Store) -> None:
    if not store.expenses:
        print("\nNo expenses yet.")
        return
    month = prompt("Month (YYYY-MM)", parse_month, default=date.today().strftime("%Y-%m"))
    items = [e for e in store.expenses if e["date"][:7] == month]
    if not items:
        print(f"No expenses in {month}.")
        return
    totals = defaultdict(Decimal)
    for e in items:
        totals[e["category"]] += e["amount"]
    total = sum(totals.values(), Decimal("0"))
    print(f"\nSummary for {month}")
    print("-" * 60)
    for cat, amt in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
        share = amt / total
        bar = "█" * max(1, round(float(share) * 20))
        print(f"{cat[:15]:<15} {money(amt):>13} {float(share) * 100:5.1f}%  {bar}")
    print("-" * 60)
    print(f"{'Total':<15} {money(total):>13}   ({len(items)} expenses)")
    budget_status(store, month)


def set_budget(store: Store) -> None:
    current = money(store.budget) if store.budget is not None else "none"
    print(f"Current monthly budget: {current}")
    text = ask("New monthly budget (blank to remove, 'cancel' to keep): ")
    if text == "":
        with store.transaction():
            store.budget = None
        print("✓ Budget removed")
        return
    while True:
        try:
            value = parse_amount(text)
            break
        except ValueError as exc:
            print(f"  ✗ {exc}")
            text = ask("New monthly budget: ")
    with store.transaction():
        store.budget = value
    print(f"✓ Monthly budget set to {money(value)}")


def export_csv(store: Store) -> None:
    if not store.expenses:
        print("\nNothing to export.")
        return

    def safe(cell: str) -> str:   # block spreadsheet formula injection
        return "'" + cell if cell[:1] in ("=", "+", "-", "@") else cell

    with open(EXPORT_FILE, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "date", "amount", "category", "description"])
        for e in sorted(store.expenses, key=lambda e: (e["date"], e["id"])):
            writer.writerow([e["id"], e["date"], f"{e['amount']:.2f}",
                             safe(e["category"]), safe(e["description"])])
    print(f"✓ Exported {len(store.expenses)} expenses to {EXPORT_FILE.name}")


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------
MENU = [
    ("1", "Add expense", add_expense),
    ("2", "View expenses", list_expenses),
    ("3", "Search", search_expenses),
    ("4", "Edit expense", edit_expense),
    ("5", "Delete expense", delete_expense),
    ("6", "Monthly summary", summary),
    ("7", "Set monthly budget", set_budget),
    ("8", "Export to CSV", export_csv),
    ("0", "Exit", None),
]


def main() -> None:
    store = Store(DATA_FILE)
    print("=" * 40)
    print("   PERSONAL EXPENSE TRACKER")
    print("=" * 40)
    actions = {key: func for key, _, func in MENU}
    while True:
        print()
        for key, label, _ in MENU:
            print(f"  {key}. {label}")
        try:
            choice = ask("\nChoose an option: ")
        except Cancel:
            break
        if choice == "0":
            break
        action = actions.get(choice)
        if action is None:
            print("  ✗ Please enter a number from the menu.")
            continue
        try:
            action(store)
        except Cancel:
            print("Cancelled. Nothing was changed.")
        except OSError as exc:
            print(f"✗ File error: {exc}. Your data was not changed.")
    print("Goodbye! Your data is saved in expenses.json")


if __name__ == "__main__":
    main()
