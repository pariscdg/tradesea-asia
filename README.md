# TradeSea Asia

Open **TradeSeaAsia.exe** to choose accounts and a lockout duration.

- The panel refreshes the saved TradeSea browser login. Use **Sign in** if needed.
- **All Lucid accounts** is selected by default, including new Lucid accounts added later.
- Choose a duration from **1, 2, 4, 6, 8, 12, or 24 hours**. The default is 12 hours.
- Duration is disabled while a selected account is locked or its lockout status cannot be verified.
- Click **Save for scheduled run**. Saving does not start a lockout.

The Windows task `tradesea-asia` runs Sunday–Thursday at 4:00 PM, using this computer's local time. It refreshes the saved login, applies the saved settings, confirms each account's lockout, and exits. Keep the computer available and signed in for the scheduled run.

Opening the panel or changing account selection does not remove an active lockout. Each account keeps its existing deadline. There is no periodic lockout repair process.

The application is packaged and obfuscated. Local controls cannot prevent the computer's owner from disabling or replacing the application.

`TradeSeaAsia.exe --self-check` runs an offline installation check without contacting TradeSea.
