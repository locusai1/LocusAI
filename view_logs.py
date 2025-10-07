import os

LOG_DIR = "logs"

def list_logs():
    """List all businesses that have logs."""
    if not os.path.exists(LOG_DIR):
        print("No logs found yet.")
        return []
    files = os.listdir(LOG_DIR)
    businesses = [f.replace(".txt", "").replace("_", " ") for f in files if f.endswith(".txt")]
    return businesses

def view_log(business_name):
    """Show log content for a specific business."""
    safe_name = business_name.replace(" ", "_").lower()
    path = os.path.join(LOG_DIR, f"{safe_name}.txt")
    if not os.path.exists(path):
        print(f"No logs found for {business_name}")
        return

    print(f"\n--- Conversation Log: {business_name} ---\n")
    with open(path, "r") as f:
        print(f.read())
    print("\n--- End of Log ---\n")

def run():
    businesses = list_logs()
    if not businesses:
        return

    print("Available logs:")
    for b in businesses:
        print(" -", b)

    choice = input("\nWhich business log do you want to view? ").strip()
    view_log(choice)

if __name__ == "__main__":
    run()

