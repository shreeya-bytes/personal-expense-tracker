
# Personal Expense Tracker

expenses = []

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

def main():
    print("==============================")
    print("   PERSONAL EXPENSE TRACKER")
    print("==============================")

    while True:
        print("\n1. Add Expense")
        print("2. Exit")

        choice = input("Enter your choice: ")

        if choice == "1":
            add_expense()

        elif choice == "2":
            print("Thank you for using the tracker!")
            break

        else:
            print("Invalid choice. Try again.")

main()
