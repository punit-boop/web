# AKF Website — Fix Notes

## What was actually broken

The zip contained a `requirements.txt` (Flask, pandas, Werkzeug) and a frontend
that was already coded to call routes like `/login`, `/register`,
`/api/announcements`, `/api/fund`, `/api/members`, `/api/contact`, etc. —
but **there was no backend at all** (no `.py` files anywhere in the zip).
That's why registration, login, the member dashboard, the live donation
counter, and the contact form all appeared "broken": every one of those was
calling an endpoint that returned a 404.

I added the missing backend (`app.py`) and fixed a couple of smaller bugs:

1. **Missing Flask backend** — implemented every route the frontend already
   expected: register → OTP verification → login → member dashboard, plus
   the `/api/*` endpoints for announcements, the fund counter, the member
   directory, and the contact form. Data is stored in simple JSON files
   under `data/` so it runs with no external database.
2. **`login.html` had a broken instant redirect** — it did
   `<meta http-equiv="refresh" content="0; url=/login">`, which immediately
   forwarded to `/login` before that route even existed, and even after
   fixing the backend this made the page flash and vanish before anyone
   could read it. Removed the redirect so the page displays normally and
   the "Sign In →" button takes you to the real login form.
3. **Duplicate/conflicting contact-form handler** — `script.js` had its own
   submit handler for `#contact-form` that raced with the one already
   written inline in `contact.html`. Both called `preventDefault()`, so the
   button text and success state were fighting each other. Removed the
   duplicate in `script.js`; `contact.html`'s handler (which now actually
   has a working `/api/contact` to post to) is the only one left.
4. Moved `register.html` and `otp_verify.html` into `templates/`, since they
   use Jinja placeholders (`{{ }}`, `{% %}`) and need to be rendered by
   Flask, not served as static files. Added `templates/login_form.html`,
   the actual login form (the old `login.html` was only ever a teaser page
   linking to a login route that never existed).

## How to run it

```bash
pip install -r requirements.txt
python app.py
```

Then visit `http://127.0.0.1:5000`.

## Notes / things you should know

- **No email service is wired up.** Registration OTPs and contact-form
  submissions are written to the server log / `data/contacts.json` instead
  of being emailed. Search `app.py` for `[DEV ONLY]` to find where to plug
  in a real mail provider (SendGrid, SES, SMTP, etc.) before this goes live.
- **The registration form lets anyone pick "Administrator" as their account
  type** and get board-level access. That's how the form was already built
  (I didn't add or remove that), but you'll probably want to lock that down
  — e.g. require an invite code or have an existing board member promote
  people — before real users register.
- `app.secret_key` in `app.py` is a placeholder. Set a real secret via an
  environment variable before deploying.
- Storage is flat JSON files under `data/` for simplicity. Fine for a small
  site; swap in a real database if usage grows.
