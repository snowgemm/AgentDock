package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.net.ApiResult
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class ApprovalRepositoryTest {
    private lateinit var server: MockWebServer
    private lateinit var repository: HttpApprovalRepository
    private val digest = "a".repeat(64)

    private val approvalJson = """
        {"id":"ap-1","task_id":"t-1","tool":"test_send_note","target":"sandbox/alice","risk":"consequential",
         "summary":"Send a note to sandbox/alice","key_args":{"body":"hello","count":3},"digest":"${"a".repeat(64)}",
         "policy_version":"v1","status":"PENDING","expires_at":"2030-01-01T00:00:00Z",
         "created_at":"2029-12-31T23:00:00Z","decided_at":null}
    """.trimIndent()

    @Before
    fun setUp() {
        server = MockWebServer().also { it.start() }
        repository = HttpApprovalRepository(OkHttpClient(), server.url("/"), Json { ignoreUnknownKeys = true })
    }

    @After
    fun tearDown() = server.close()

    @Test
    fun listMapsTheExactActionTheApproverWillSee() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body("[$approvalJson]").build())

        val approval = (repository.list("t-1") as ApiResult.Success).value.single()

        assertEquals("/api/v1/tasks/t-1/approvals", server.takeRequest().url.encodedPath)
        assertEquals("test_send_note", approval.tool)
        assertEquals("sandbox/alice", approval.target)
        assertEquals(ApprovalRisk.CONSEQUENTIAL, approval.risk)
        assertEquals(listOf("body" to "hello", "count" to "3"), approval.keyArgs)
        assertEquals(digest, approval.digest)
        assertTrue(approval.isActionable(nowMs = 1_000L))
    }

    @Test
    fun expiredOrAlreadyDecidedApprovalsAreNotActionable() {
        val base = Json { ignoreUnknownKeys = true }.decodeFromString(ApprovalDto.serializer(), approvalJson).toDomain()
        assertFalse(base.copy(status = ApprovalStatus.APPROVED).isActionable(1_000L))
        assertFalse(base.isActionable(nowMs = base.expiresAtMs + 1))
        assertEquals(ApprovalStatus.UNKNOWN, ApprovalStatus.fromWire("SOMETHING_NEW"))
        assertEquals(ApprovalRisk.UNKNOWN, ApprovalRisk.fromWire("catastrophic"))
    }

    @Test
    fun decideSendsTheDisplayedDigestAndTheChosenDecision() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body(approvalJson.replace("PENDING", "APPROVED")).build())
        server.enqueue(MockResponse.Builder().code(200).body(approvalJson.replace("PENDING", "DENIED")).build())

        val approved = (repository.decide("ap-1", digest, approve = true) as ApiResult.Success).value
        val approveRequest = server.takeRequest()
        val denied = (repository.decide("ap-1", digest, approve = false) as ApiResult.Success).value
        val denyRequest = server.takeRequest()

        assertEquals("/api/v1/approvals/ap-1/decision", approveRequest.url.encodedPath)
        assertEquals("""{"decision":"approve","digest":"$digest"}""", approveRequest.body!!.utf8())
        assertEquals("""{"decision":"deny","digest":"$digest"}""", denyRequest.body!!.utf8())
        assertEquals(ApprovalStatus.APPROVED, approved.status)
        assertEquals(ApprovalStatus.DENIED, denied.status)
    }

    @Test
    fun changedOrExpiredActionsSurfaceAsConflictNotSuccess() = runTest {
        server.enqueue(MockResponse.Builder().code(409).body("""{"detail":"digest_mismatch"}""").build())
        server.enqueue(MockResponse.Builder().code(404).build())
        server.enqueue(MockResponse.Builder().code(401).build())

        assertEquals(ApiResult.Failure(ApiError.Conflict), repository.decide("ap-1", digest, true))
        assertEquals(ApiResult.Failure(ApiError.NotFound), repository.decide("ap-1", digest, true))
        assertEquals(ApiResult.Failure(ApiError.AuthRequired), repository.decide("ap-1", digest, true))
    }
}
