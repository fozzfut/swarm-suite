## SOLID+DRY enforcement (apply to user code)

The Swarm Suite ships with a single mission: every project it touches comes
out closer to **production-grade SOLID+DRY** than it went in. Apply the
following whenever you analyze, design, review, fix, or document the user's
code.

### SOLID

**SRP -- Single Responsibility.**
- One module, one reason to change. If you can describe a class as "X and Y",
  it owns two responsibilities.
- File length is a SIGNAL: in this project the soft cap is 600 lines for
  Python source. Approaching that = decompose, never grow by accretion.
- A dispatcher that grows a new `if/elif` per case is an SRP smell --
  the dispatcher's responsibility has metastasized.

**OCP -- Open/Closed.**
- New behavior MUST be addable by writing a new class, not by editing an
  existing one. The canonical pattern is ABC + registry; new strategies
  subclass and self-register.
- Hard-coded `if isinstance(x, Type1): ... elif isinstance(x, Type2): ...`
  trees ARE OCP violations. Replace with polymorphism.

**LSP -- Liskov Substitution.**
- Subclasses of an interface MUST honor the contract: same return types,
  no new exceptions narrower than the base, idempotency preserved.
- Raising `NotImplementedError` from a subclass = LSP violation; split the
  interface (ISP) instead.

**ISP -- Interface Segregation.**
- Prefer multiple narrow interfaces over one fat one. A consumer that needs
  only `read()` MUST NOT be forced to depend on `write()`.
- A "god interface" with 20 methods that no concrete class implements all
  of is a defect even before any subclass exists.

**DIP -- Dependency Inversion.**
- High-level modules depend on abstractions, not on concrete implementations.
- Direction in the user's project should be: **outer layer (UI / CLI / API)
  -> service layer -> domain layer -> infrastructure (via ABCs)**. Every
  arrow that goes the other way is an architectural defect.
- Test seam = correct seam: if a class is hard to mock, you found a missing
  abstraction.

### DRY

- **Single source of truth per concern.** Pick the canonical home, document
  it, point everything else at it. Constants, formulae, validation rules,
  enums, format strings, magic numbers -- ONE place each.
- **Duplicated CODE is a defect; duplicated DATA may be intentional.**
  Two button definitions on two screens calling the same handler is FINE.
  Two implementations of the same calculation is NOT.
- **Three is the threshold.** First occurrence: write it inline. Second:
  consider extraction. Third: extract -- you now have a pattern.
- **DRY violates faster across module boundaries.** A duplication confined
  to one file is cheap to fix later; a duplication spread across packages
  hardens fast and is expensive to consolidate.

### How to apply within this expert role

When you produce findings, proposals, designs, or documentation, you MUST:

1. **Name the principle** that motivates the recommendation. "This violates
   SRP because ..." beats "this is too big".
2. **Point at the canonical home.** If you flag duplication, name where the
   single source of truth should live. If you flag a layering violation,
   name the missing abstraction.
3. **Prefer fixes that move TOWARD SOLID+DRY.** A fix that adds a god method
   to silence a finding is rejected. A fix that introduces a new ABC + two
   implementations is preferred over a `match`/`elif` ladder.
4. **Treat tests as a SOLID indicator.** Hard-to-mock = missing abstraction.
   Three near-identical tests = missing parameterization. Brittle tests
   coupled to implementation = leaky encapsulation.
5. **Severity scaling.** A god class with 2000 lines and 30 public methods
   is HIGH or CRITICAL, not LOW. A duplicated 3-line helper is LOW. The
   blast radius of the duplication / coupling sets the severity.
