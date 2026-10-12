# Example answers (unedited)

Taken verbatim from the final evaluation run (`eval/reports/answers.jsonl`). Bracketed numbers refer to the source excerpts shown with each answer in the CLI and the app.

## What is the deadline for submitting a suspicious transaction report once suspicion is established?

The STR must be filed within the next working day from the date suspicion is established [3, 6].

- "STRs shall be promptly filed within the next working day from the occurrence thereof." The Reporting Period rule defines "Occurrence" as "the date of establishment of suspicion or determination of the suspicious nature of the transaction" [3].
- The 2018 IRR states the same standard: "STRs shall be promptly filed within the next working day from occurrence thereof, which for purposes of this Rule, shall be the date of establishment of suspicion or determination of the suspicious nature of the transaction" [6].
- Note: this next-working-day deadline runs from the date suspicion is *established*; separate "Determination Period" rules [2, 5] govern how long a covered person has to establish that suspicion in the first place, depending on the trigger (e.g., up to 60 calendar days for TMS-generated alerts [1] or ZSTR triggers [4], up to 60 calendar days generally for unlawful-activity-related transactions [5], or 10–60 days for AMLC referrals depending on whether a specific unlawful activity is identified [2]).

*Cited provisions:* irr2018:rule22:sec2, rrg2021:partiv:sd, rrg2021:partiv:sd:sb, rrg2021:partiv:sd:sc, rrg2021:partiv:sd:se, rrg2021:partiv:sd:sf  ·  *verifier:* flagged STRs shall be promptly filed within the next working day from the occurrence thereof.  ·  *refused:* False

## How long does a covered person have to determine suspicion for transactions flagged by the transaction monitoring system?

Sixty (60) calendar days from the date of the transaction, arising from TMS-generated alerts [2].

- The 2021 RRG states: "Covered persons shall establish the suspicion or determine the suspicious nature of the transaction, or any attempt thereof, within sixty (60) calendar days from the date of the transaction, arising from TMS-generated alerts and based on any periodic run inclusive of certain number of transaction dates" [2].
- The periodic run used to generate these alerts must not be longer than thirty-one (31) consecutive calendar days at any given time [2, 6].
- This 60-day rule is distinct from the 10-day rule for Section 3(b-1)/Rule 3.a.15 suspicious circumstances [4], the 10/60-day rule for AMLC referrals [3], and the 60-day rule for unlawful-activity-related transactions [1].

*Cited provisions:* rrg2021:partiv:sc, rrg2021:partiv:sd:sa, rrg2021:partiv:sd:sb, rrg2021:partiv:sd:sc, rrg2021:partiv:sd:se  ·  *verifier:* pass  ·  *refused:* False

## What should an insurer do before paying out a life policy when a beneficiary is a higher-risk PEP?

Before paying out, the insurer must inform senior management and conduct enhanced scrutiny, and consider filing an STR [1].

- Covered persons must "take reasonable measures to determine whether the beneficiaries and the beneficial owner of the beneficiary, are PEPs," occurring "at the latest, at the time of the payout" [1].
- "Where higher risks are identified, covered persons shall inform senior management before the payout of the policy proceeds, to conduct enhanced scrutiny on the whole business relationship with the policyholder, and to consider filing an STR" [1].
- If the beneficiary is a juridical person or legal arrangement assessed as higher risk, the insurer must also take "reasonable measures to identify and verify the identity of the beneficial owner of the beneficiary, at the time of payout" [1].

*Cited provisions:* irr2018:rule19:sec2  ·  *verifier:* pass  ·  *refused:* False

## What is the BSP's de minimis threshold amount for cross-border wire transfers?

NOT_IN_SOURCES
The excerpts state that a de minimis threshold for cross-border wire transfers exists and is "as determined by the BSP" [1], but none of the excerpts provide the actual threshold amount.

*Cited provisions:* —  ·  *verifier:* pass  ·  *refused:* True

## Can a covered person tell a customer that an STR has been filed about them?

No, STR filing must be kept confidential and not disclosed to the customer [1, 6].

- Covered persons who suspect ML/TF but believe pursuing CDD would "tip-off the customer" need not continue CDD, but must "file an STR, closely monitor the account, and review the business relationship" [1] — without alerting the customer.
- Internal controls must affirmatively prevent disclosure: covered persons "shall ensure that proper controls are in place to guarantee confidentiality and that no 'tipping – off' of customers will happen at all times during the entire process" [6].

*Cited provisions:* irr2018:rule18:sec13, rrg2021:partiv:sc  ·  *verifier:* pass  ·  *refused:* False
