"""DEPRECATED — do not use.

This script used to patch Alpha_Move_AI_User_Manual.docx in place with hand-coded
python-docx edits. That approach is exactly why the Word manual drifted out of
sync with USER_MANUAL.md.

The manual is now generated from a single source of truth:

    USER_MANUAL.md  --(build_manual.py)-->  Alpha_Move_AI_User_Manual.docx

To update the manual:
    1. Edit USER_MANUAL.md
    2. Run:  python build_manual.py
    3. Deploy:  python backend/upload_help_doc.py   (needs backend/.env DB creds)
"""

import sys

if __name__ == "__main__":
    sys.exit(
        "update_doc.py is deprecated. Edit USER_MANUAL.md and run "
        "`python build_manual.py` instead."
    )
