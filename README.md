Personal Expense Tracker

A simple, reliable command-line app to track your spending. Pure Python, no dependencies.

Features
Add, view, search, edit and delete expenses
Monthly summary by category with percentages and bars
Monthly budget with warnings (80% used / over budget)
Export to CSV (Excel-friendly)
Requirements

Python 3.8 or newer.

Run
bash
python main.py
Menu
Option	Action
1	Add expense
2	View expenses (all or by month)
3	Search by description or category
4	Edit expense
5	Delete expense (asks to confirm)
6	Monthly summary
7	Set monthly budget
8	Export to expenses_export.csv
0	Exit

Type cancel (or press Ctrl+C) at any prompt to go back without changing anything.

Data safety
Money is stored with Decimal, so totals are always exact.
All input is validated; invalid entries are re-prompted.
Saves are atomic, so a crash can't corrupt expenses.json.
If expenses.json is damaged, a timestamped backup is created before starting fresh.
expenses.json is listed in .gitignore so your financial data is not pushed to GitHub.
Files
main.py - the application
expenses.json - your data (created/updated automatically)
expenses_export.csv - created when you export