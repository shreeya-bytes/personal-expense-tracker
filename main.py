
# Personal Expense Tracker

expenses = []

# Feature 1: Add Expense
def add_expense():
    print("\n--- Add New Expense ---")

    amount = float(input("Enter amount: ₹"))
    category = input("Enter category: ")
    description = input("Enter description: ")

    expense = {
        "amount": amount,
        "category": category,
        "description": description
    }

    expenses.append(expense)

    print("\nExpense added successfully!")


# Feature 2: View Expenses
def view_expenses():
    print("\n--- Your Expenses ---")

    if not expenses:
        print("No expenses recorded yet.")
        return

    for index, expense in enumerate(expenses, start=1):
        print(f"\nExpense {index}")
        print("Amount:", expense["amount"])
        print("Category:", expense["category"])
        print("Description:", expense["description"])


# Feature 3: Calculate Total
def calculate_total():
    total = 0

    for expense in expenses:
        total += expense["amount"]

    print("\nTotal Spending: ₹", total)


# Main Menu
def main():
    print("==============================")
    print("   PERSONAL EXPENSE TRACKER")
    print("==============================")

    while True:
        print("\n1. Add Expense")
        print("2. View Expenses")
        print("3. View Total Spending")
        print("4. Exit")

        choice = input("Enter your choice: ")

        if choice == "1":
            add_expense()

        elif choice == "2":
            view_expenses()

        elif choice == "3":
            calculate_total()

        elif choice == "4":
            print("Thank you for using the tracker!")
            break

        else:
            print("Invalid choice. Try again.")


main()
