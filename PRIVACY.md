# Privacy Policy for Namma-Kanakku (KiranaFlow)

*Last updated: October 17, 2026*

Namma-Kanakku ("we", "our", or "the service") is committed to protecting the privacy, dignity, and commercial confidentiality of neighbourhood kirana store owners and their patrons.

## 1. Core Privacy Principles
- **Strict Discretion by Design**: Customer account balances, debt totals, and credit limit warnings are never broadcast or spoken aloud into physical retail environments. Such information is rendered solely on private visual displays (`screen_note` and the `ui://khata-card` MCP Apps widget).
- **Zero Third-Party LLM Leakage**: The Namma-Kanakku MCP backend performs all catalog lookups, phonetic matching, and accounting arithmetic using local, deterministic SQLite operations. No customer names, phone numbers, or ledger balances are transmitted to external large language model APIs.
- **Local / Ephemeral Storage**: Data is maintained in the merchant's dedicated SQLite database instance. In demo environments, all customer names, phone numbers, and transaction logs are clearly marked as simulated test fixtures (`[DEMO DATA - NOT REAL]`).

## 2. Information Handled
When integrated with Alexa+ or compatible MCP clients, the service handles:
- Customer identifiers (e.g., customer name or shop alias).
- Spoken grocery catalog requests and quantities (in English, Tamil, or Tanglish).
- Cash or digital payments credited against ledger accounts.
- Shopkeeper custom catalog prices and item aliases.

## 3. How Information is Used
Information is processed strictly to:
- Maintain double-entry credit/debit records (*khata*).
- Perform deterministic phonetic item matching.
- Facilitate reversible transaction undos and overdue account tracking.

## 4. Data Sharing & Third Parties
Namma-Kanakku does not sell, license, rent, or trade merchant or customer data with any advertisers, brokers, or third parties.

## 5. Contact
For questions regarding this privacy policy or open-source compliance, please visit our repository:
[monishchandran2007-hub/Namma-Kanakku](https://github.com/monishchandran2007-hub/Namma-Kanakku)
