# Data Dictionary

## `loads.csv`: TMS load change feed

Each time a load is created or changed in the TMS, the feed sends the **full record** again. A load can therefore appear many times. The file is not in any particular order, and the feed sometimes re-sends a record it already sent.

| Field | Type | Description |
|---|---|---|
| `load_id` | string | Unique load identifier. |
| `status` | string | `Open`, `Covered`, `In Transit`, `Delivered`, `Cancelled`. |
| `carrier_dot` | string | Carrier's USDOT number. **Typed in by hand by our reps**, so formatting varies. Blank until a carrier is assigned. |
| `origin_city`, `origin_state` | string | Pickup location. |
| `dest_city`, `dest_state` | string | Delivery location. |
| `pickup_ts` | timestamp | Scheduled pickup time, **in UTC**. |
| `customer_rate` | decimal | Linehaul amount the customer pays us (USD). |
| `accessorial_revenue` | decimal | Extra charges billed to the customer, e.g. detention or lumper (USD). **Blank means 0.** |
| `carrier_cost` | decimal | Total amount we pay the carrier (USD). Can change after delivery when costs are corrected. Blank until a carrier is assigned. |
| `margin` | decimal | **Legacy field, do not use for reporting.** Computed as `customer_rate − carrier_cost` and leaves out accessorials. |
| `last_modified` | timestamp | When this version of the record was written, in UTC. |

## `fmcsa_carriers.csv`: FMCSA census snapshot

One row per carrier.

| Field | Type | Description |
|---|---|---|
| `dot_number` | integer | USDOT number. |
| `legal_name` | string | Carrier's legal name. |
| `authority_status` | string | `ACTIVE`, `REVOKED` or `INACTIVE`. |
| `status_date` | date | Date the current `authority_status` took effect. |

## Business rules

1. **Current state of a load:** the version with the latest `last_modified`.
2. **Reporting date:** all of our reporting runs on **US Eastern time** (`America/New_York`). "October 2026" means a pickup date between Oct 1 and Oct 31 in Eastern time.
3. **Revenue** = `customer_rate + accessorial_revenue`.
4. **Gross margin** = revenue − `carrier_cost`.
5. **Unauthorized load:** the carrier's `authority_status` is `REVOKED` or `INACTIVE`, **and** its `status_date` is on or before the load's pickup date. A carrier revoked *after* the pickup was authorized when it hauled that load.
6. **Unverified load:** the load's carrier DOT doesn't match any row in the FMCSA file. Keep these loads in the scorecard.
