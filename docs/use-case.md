# RouteMind AI: use case and user guide

## The problem

Choosing a freight route involves more than finding the lowest price. A shipment may require fragile handling, enough pallet capacity, a delivery deadline and a limit on transfers. A cheaper option may arrive later, while a faster option may exceed the budget. When requirements change, a planner needs to understand the effect without rebuilding the request from scratch.

RouteMind demonstrates how a conversational planning assistant can make those choices easier to review. It turns a shipment request into route options, explains the recommendation and supports follow-up questions within the same planning conversation.

## Example: fragile electronics from Fremont to Austin

A logistics coordinator needs to move 15 pallets of fragile electronics with a budget of $4,000. Their initial priority is price, but they also want to understand the cost of faster delivery.

| Step | What the planner does | What to review |
|---|---|---|
| Describe the need | Ask for the cheapest route for the shipment. | Confirm the interpreted origin, destination, quantity, budget and cargo requirements. |
| Resolve uncertainty | Answer any missing-detail questions. | Check that the completed request reflects the actual intent. |
| Review the recommendation | Inspect Fremont → Phoenix → Austin at $2,100 in the seeded scenario. | Compare transport and transfer costs, arrival time and handling requirements. |
| Explore a trade-off | Ask “Make it faster, but keep the budget.” | Compare the direct service at $3,400 with the earlier recommendation. |
| Make a decision | Choose which option best fits the business need. | Treat the result as a demonstration, not a quote or confirmed booking. |

These outcomes apply to the supplied demo scenario. Different quantities or constraints can produce different results.

## Reading a result

**Recommendation and alternatives:** Look at the full journey, including transfers, total price and arrival time. The best option depends on the objective you selected and the requirements you supplied.

**Interpreted requirements:** Review what RouteMind understood before relying on the result. Use the structured controls to make exact requirements explicit when needed.

**Supporting evidence:** Carrier passages and handling guidance provide context for the recommendation. Evidence is supporting information, not a guarantee that a real carrier will accept the shipment.

**Follow-up comparison:** A revised plan shows what changed and how the result compares with the earlier recommendation. Earlier results remain available in the request history.

**No feasible route:** This means the available demo services cannot satisfy the current requirements. Where a verified single change can help, RouteMind offers it for review. A suggestion is applied only when you choose it; some requests have no available suggestion.

## Useful follow-up questions

- “Make it faster, but keep the budget.”
- “What if we ship only eight pallets?”
- “Can we arrive earlier without spending more than $500 extra?”
- “Prefer direct, but one transfer is okay if it saves at least $500.”

Review the interpreted changes each time. Permission to spend more relative to a previous plan does not automatically remove an existing budget ceiling.

## Exploring the available data

Open **Data explorer** in the sidebar to browse hubs, carriers, handling capabilities, schedules and evidence documents. Search for a location, carrier or document, then select **View** to inspect the complete record. The explorer also lets interested reviewers inspect the stored evidence vectors.

The explorer is read-only and excludes shipment conversations. All displayed reference data is synthetic. It helps explain the demo's inputs; it is not a live logistics dashboard.

## Asking about carrier policies

Choose **Carrier policies** in the sidebar when you want to understand the available documents before planning. Enter a question such as “What handling is described for fragile electronics?” Select one carrier to narrow the search or two to compare their documented descriptions.

When a language model is configured, the page shows selected passages with source links and any unanswered parts of the question. Open a source to check its full wording and version. If the documents do not specify packaging, temperature ranges or guarantees, do not assume those requirements are satisfied. Missing documentation is not evidence that a service is prohibited.

Without a configured model, the page shows related passages for manual review and clearly labels them as search results. All evidence is synthetic. This feature does not change carrier eligibility, prices or schedules, and each question starts a fresh review.

## What a project review should demonstrate

- A complete shipment request produces an understandable route recommendation within the stated requirements.
- Missing information prompts a clarification rather than an unsupported assumption.
- A follow-up preserves unchanged requirements and makes the resulting trade-off visible.
- An infeasible request is reported clearly, with verified adjustment options where available.
- Supporting evidence and reference records can be inspected.

These are demonstration acceptance goals, not claims of measured savings, real-world accuracy or service availability.

## Current boundaries

The project covers a single ground freight shipment and up to three scheduled legs. Its fixed scenario runs November 1–7, 2026. It does not use live traffic, weather, tracking, freight prices or capacity, and it does not book or reserve services. Real-time integrations are deferred.

Use synthetic shipment examples when reviewing the shared demo. Real operational use would require current, authorized data and further production work.

[Back to the README](../README.md) · [Local setup](../README.md#run) · [Technical architecture](architecture.md)
