"""
Small command-line helper for one-off admin tasks -- currently just creating
coach accounts, since there's no self-registration flow (manually-created
accounts were the easier of the two options, and the user confirmed either
was fine).

Usage:
    python3 manage.py add-coach <username> "<Display Name>" <password>

Run this once locally before your first deploy to seed data/coaches.json,
then commit that file (see the README for why that one file is safe and
necessary to commit even though the rest of data/ is gitignored). Run it
again any time you need to add another coach.
"""
import sys
import store


def main():
    if len(sys.argv) != 5 or sys.argv[1] != 'add-coach':
        print(__doc__)
        sys.exit(1)
    _, _, username, display_name, password = sys.argv
    store.add_coach(username, display_name, password)
    print(f"Coach '{username}' ({display_name}) created/updated in data/coaches.json.")
    print("Remember to commit and push data/coaches.json so this account survives a redeploy.")


if __name__ == '__main__':
    main()
