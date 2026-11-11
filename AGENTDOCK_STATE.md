# AgentDock one-run state (branch test)
- Stage 1 (Android OIDC → session): code + docs written; commit pending/see git log. Done once pushed and CI green.
- Key files: app/.../data/auth/** (pure logic, JVM-tested locally), data/auth/android/** (AppAuth, Keystore, DataStore), AppContainer.kt, ui/auth/AuthViewModel.kt, ui/screens/AccountSection.kt.
- Decisions: OkHttp 5.5.1 + okhttp-sse, kotlinx.serialization 1.12.0, AppAuth 0.11.1; Keystore AES-GCM (no security-crypto); no java.time (minSdk 23) -> data/net/Iso8601.kt.
- Existing Settings "server URL" field is unused by the API client: API base URL comes only from agentdockApiBaseUrl build config.
- Local checks: no Android SDK (Google hosts blocked); pure Android-free logic compiled+tested via a scratch JVM Gradle project. Android CI is the gate for UI/Android code.
- Backend local: Postgres 16 + venv work (43 tests passed baseline).
- Blockers: OIDC provider registration; Android CI result unknown until pushed.
- Next: Stage 2.
