Frontend Prompt

Build a modern, decision-first job search dashboard for a single user.

Primary goal:
- Streamline the user's job-finding process by surfacing the most compatible, highest-paying jobs with the best odds of getting an interview.

Core UX requirements:
- Show local jobs and nationwide recommendations side by side.
- Make the page understandable to a non-technical user.
- Prioritize fast first paint and progressive loading.
- Default to showing the best jobs first using expected value and fit.
- Support dark mode.

UI priorities:
- Strong visual hierarchy.
- Clear salary, work type, location, distance, and job source.
- Simple search controls: ZIP, distance, minimum salary, work mode.
- Sorting and filtering should be lightweight and easy to scan.
- Every score must have explainability.

Required score surfaces:
- Compatibility
- Interview potential
- Sentiment
- Expected Value (EV)
- Friction
- Confidence

Required explainability:
- "Why this score?" popovers for interview and compatibility.
- Strategy guide section explaining:
  - Apply now
  - Tailor lightly
  - Tailor heavily
  - Reach out first
  - Save for later
  - Skip
- Bottom-of-page glossary for EV, Friction, and Confidence.

Behavior requirements:
- Search local jobs first so the UI becomes useful quickly.
- Fill in nationwide results after local results load.
- Avoid long blank loading states.
- Treat the dashboard like a personalized Indeed-style command center, not a developer tool.

Implementation constraints:
- Next.js App Router
- React client components where needed
- Tailwind + existing UI primitives
- Keep existing dashboard style, but make it more decision-oriented and faster
- Preserve exact job description access and links to original listings
