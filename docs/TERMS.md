# Terms of use (proposal)

Last updated: 2026-10-19. **Draft for the team and counsel to review; not published in the app yet.** It describes what the software in this repository does today, so every promise below points at code. It is not legal advice. The privacy side (what is stored, where, for how long, who receives it) is in [PRIVACY.md](PRIVACY.md); these terms refer to it rather than repeat it.

## 1. Who offers the service

Neural Ledger is a prototype built for FinTechathon 2026 (Topic A) and run by `[team or legal entity name]`, contact `[contact email]`. Fill both in before publishing.

## 2. What Neural Ledger is

An AI cash-flow copilot running in a **sandbox**. It can:

- forecast your cash flow over the coming months and tell you how much you can spend or save while keeping a liquidity floor;
- simulate a purchase, including one paid in cuotas, against that forecast;
- suggest a savings plan within the profile your answers and your finances permit;
- answer your questions in a chat, using only figures computed by its financial engine;
- read bank statements (cartolas) you upload and sort their lines into spending categories, which you can change;
- after your confirmation, create a savings rule or set your own liquidity floor **in the sandbox bank**.

## 3. What it is not

- **Not a bank and not real money.** The bank is simulated. No transfer, debit or payment reaches a real account. A savings rule or a floor is a record in the sandbox.
- **Not financial advice.** The figures are estimates from your data and fixed parameters. They can be wrong, and nothing the app shows is a recommendation to buy, borrow, invest or save. No amount is ever described as safe. Decide with your own judgement or a licensed adviser.
- **Not a production service.** It is a hackathon prototype, offered as is, with no promise of availability, continuity or keeping your data (section 9).

## 4. Who may use it

You must be **18 or older**. The app does not check age yet (Ley 21.719 art. 16 quáter); by creating an account you confirm you are an adult. One person per account.

## 5. Your account

- Sign-up needs an email, a display name (1 to 40 letters) and a password of at least 10 characters. The password is stored only as a scrypt hash.
- The email must be a permanent address. Sign-up refuses disposable inboxes (yopmail, temp-mail, mailinator and the others on a maintained public list) and domains that do not exist or receive no mail. The address is not confirmed by email, so the check does not prove you own it.
- A session lasts 12 hours and is never extended. Keep your password to yourself and sign out on a shared device.
- **Shared demo personas.** "Explore a demo persona" opens Camila or Diego, synthetic profiles shared by every visitor. Anything you upload there is visible to the other visitors of that persona until someone resets it. Do not put anything of yours in a persona.

## 6. The sandbox rule: no real data

At sign-up you must acknowledge the sandbox notice, and the app records which version you accepted. By accepting it you agree to:

- **upload only synthetic statements**, never a real cartola;
- **enter no real personal data**, yours or anyone else's: no real names, RUTs, account or card numbers.

Nothing can tell a real statement from a synthetic one. At import the app masks names, RUTs, account and card numbers, emails and phones by rule, but merchants, amounts and dates are kept, and they are personal data when the statement is real. If you upload real data anyway, delete it (section 9).

## 7. How the copilot works, and its limits

- **The numbers come from the engine, not from the AI.** Every amount, verdict and permission is computed by deterministic code. The language model only explains: a verifier checks that every number it says is one the engine produced and that every warning is mentioned, and replaces the reply when it is not.
- **Only you can confirm.** The copilot can propose an action but cannot carry it out. You confirm the exact terms in a confirmation card; what runs is what you confirmed, signed and single-use. A liquidity floor is accepted only if you wrote that amount yourself.
- **Suitability.** A plan never goes beyond the lower of the risk you declared in the questionnaire and what your finances permit. Until you answer the questionnaire, the conservative profile is used.
- **Known limits of the engine today:**
  - the savings plan does not always grow with a higher profile, and a purchase can, in some cases, raise the planned amount (ADR-014, pending a team decision);
  - a plan tells you, in the chat, the risk you declared, what your finances permit and what limits them, but there is no suitability report you can download (UG01).
- **The AI can misread you.** It may misunderstand a message or answer something you did not ask. It cannot move money or change your profile, but read every card before confirming.

## 8. Acceptable use

Do not:

- try to make the copilot ignore its rules, adopt another role, or reveal its instructions or keys;
- access or try to access another user's data, or flood the service (it refuses requests over its limits, for example 20 chat messages or 10 statement uploads per user in a short window, with HTTP 429);
- upload anything that is not a bank statement, or a file over 15 MB;
- use the service for anything illegal, or to process other people's data.

Text from statements and merchants is treated as data, never as instructions. The team may close an account that breaks these terms.

## 9. Your data and your rights

- What is stored, where, for how long and who receives it: [PRIVACY.md](PRIVACY.md). Personal data is encrypted at rest. With the default settings no data leaves the server, except that at sign-up the domain of your email (the part after `@`) is looked up in DNS. When the team turns on a language model or another external provider, data goes to providers **outside Chile** (Ley 21.719 art. 27); the safeguards for those transfers are not documented yet.
- **Delete your account** at any time: Profile, Delete account, with your password and the word DELETE (or your email). It deletes your account, profile, answers, statements, transactions, proposals, authorizations, savings rules and sessions at once. Your audit events are erased; the audit chain keeps only their place.
- **What the app does not do yet**, and what to do meanwhile (write to `[contact email]`):
  - export all your data in one file (G02): you can see your statements, transactions and audit events in the app;
  - correct a statement line's amount, date or description (G04): you can change its category;
  - object to or block processing (G05): stop uploading and write to the team;
  - record a separate, per-purpose consent before each import (G06): today the sandbox acknowledgement at sign-up is the only one.
- The data protection impact assessment (art. 15 ter) has not been done.
- **No retention period.** The team may delete the database at any time, for example at the end of the hackathon. Do not rely on the app to keep anything.

## 10. Responsibility

The service is a free prototype offered as is. To the extent the law allows, the team is not responsible for decisions you make based on its estimates, or for the loss of data stored in it. Nothing in these terms limits the rights Chilean law gives you as a consumer or as a data subject.

## 11. Changes and law

These terms change in this file through the repository's review, and the date at the top changes with them. Chilean law applies.

---

**For the team before publishing (remove this section):**

- Fill in section 1 and the contact in section 9.
- Publish a Spanish version: a consumer contract in Chile should be in Spanish (Ley 19.496). The app is English-first today.
- Link it from the sign-up form next to the sandbox checkbox, and decide whether accepting it is part of that checkbox. Changing what users accept means bumping `SANDBOX_NOTICE` (`application/use_cases/accounts.py`); asking existing users to accept a new version is not built.
- Section 4: an age check is not built; decide whether a checkbox at sign-up is enough.
- Re-check sections 7 and 9 against the open strict xfails (G01, G02, G04–G06, UG01–UG03, ADR-014) before each release, and remove each item as it closes. G01 (no authentication in demo mode) is not listed: it affects only local runs, never the deployed app.
- `PRIVACY.md` "Why" says forecasts do not use imported statements (ADR-029 not built), but `bootstrap/container.py` gives an account with statements its own model. Confirm which is true before publishing either document.
