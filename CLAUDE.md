## Architecure
- Layers: Django based api handler, viewset, models (entities), service handlers (for endpoints)
- Don't write anything that is not asked for. 
- use ABC, Abstract classes for interfaces
- Follow SRP: Write the classes and methods having single responsibily
- Follow LSP: Child class should implement all the functions of the base class
- Follow ISP: The interfaces (abstract classes) should not be bloated, and according to the requirement
- Follow DIP: Use Depenency/Constructor Injection only

## Logging
- stdlib logging, JSON Formatter, add extra fields with extra=, correlation_id with contextvars

## Errors
- Actionable: Good Error: coupon not redeemed {coupon: "", user_id: "" ..} error: coupon expired. 
- Error classes: AppError. Other child classes shouls inherit it. It should have the code and the message
- Every error should have code, message and correlation_id
- In except dont leave it as pass, all should be handled and raised.

## Security
- Invalidate and normalise the input at the first boundary. Reject if invalid
- Dont hardcode any config or secret

## Testing
- Pytest, for each invariant/rules please test for both happy and error cases

## Guardrails
- Don't put comment if not necessary (in very obvious code blocks)
- Add docstrings in the function definitions (showing the input, output and what the method is doing) and type hints
- for any resource (database handler, connection pools) always close the resource maybe in try/finally block
- no unused import statement, todo, dead code etc