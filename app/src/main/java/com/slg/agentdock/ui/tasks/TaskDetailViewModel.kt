package com.slg.agentdock.ui.tasks

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.net.ApiResult
import com.slg.agentdock.data.tasks.Approval
import com.slg.agentdock.data.tasks.ApprovalRepository
import com.slg.agentdock.data.tasks.LastSeenStore
import com.slg.agentdock.data.tasks.RemoteTaskDetail
import com.slg.agentdock.data.tasks.StreamState
import com.slg.agentdock.data.tasks.TaskEventStream
import com.slg.agentdock.data.tasks.TaskTimelineSync
import com.slg.agentdock.data.tasks.TaskEvent
import com.slg.agentdock.data.tasks.TaskRepository
import com.slg.agentdock.data.tasks.TimelineBuffer
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class TaskDetailUiState(
    val detail: RemoteTaskDetail? = null,
    val events: List<TaskEvent> = emptyList(),
    val loading: Boolean = false,
    val error: ApiError? = null,
    val stream: StreamState = StreamState.Idle,
    /** Highest sequence seen in an earlier visit; later events are marked new. 0 = none. */
    val lastSeenAtOpen: Long = 0L,
    val approvals: List<Approval> = emptyList(),
    val deciding: Boolean = false,
    val decisionError: ApiError? = null,
)

class TaskDetailViewModel(
    private val repository: TaskRepository?,
    private val stream: TaskEventStream?,
    private val lastSeen: LastSeenStore?,
    private val approvals: ApprovalRepository?,
    private val taskId: String,
) : ViewModel() {
    private val timeline = TimelineBuffer()
    private var syncJob: Job? = null
    private var detailRefreshedAtSequence = 0L
    private var approvalsLoadedAtSequence = -1L
    private val mutableState = MutableStateFlow(TaskDetailUiState())
    val state: StateFlow<TaskDetailUiState> = mutableState.asStateFlow()

    /** Explicit REST refresh: task detail plus every event after the last one seen. */
    fun refresh() {
        val repo = repository ?: return
        if (mutableState.value.loading) return
        mutableState.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            var failure: ApiError? = null
            val detail = when (val result = repo.detail(taskId)) {
                is ApiResult.Success -> result.value
                is ApiResult.Failure -> {
                    failure = result.error
                    null
                }
            }
            if (failure == null) failure = catchUpEvents(repo)
            mutableState.update {
                it.copy(
                    detail = detail ?: it.detail,
                    events = timeline.snapshot(),
                    loading = false,
                    error = failure,
                )
            }
        }
    }

    /**
     * Starts the live timeline while the screen is visible: REST catch-up, then SSE with
     * bounded reconnects. Safe to call repeatedly; call [stopStreaming] when not visible.
     */
    fun startStreaming() {
        val repo = repository ?: return
        val events = stream ?: return
        if (syncJob?.isActive == true) return
        syncJob = viewModelScope.launch {
            if (mutableState.value.lastSeenAtOpen == 0L) {
                val seen = lastSeen?.get(taskId) ?: 0L
                mutableState.update { it.copy(lastSeenAtOpen = seen) }
            }
            refreshDetailOnly(repo)
            TaskTimelineSync(repo, events, timeline).run(taskId)
                // Latest snapshot wins; the pause caps UI updates so a burst of events
                // recomposes the timeline a few times per second, not once per event.
                .conflate()
                .collect { snapshot ->
                    mutableState.update {
                        it.copy(
                            events = snapshot.events,
                            stream = snapshot.state,
                            error = snapshot.error.takeIf { _ -> snapshot.state != StreamState.Live },
                        )
                    }
                    val newest = snapshot.events.lastOrNull()
                    val statusMayHaveChanged = snapshot.state == StreamState.Ended ||
                        (newest != null && newest.sequence > detailRefreshedAtSequence &&
                            newest.payload.containsKey("to_status"))
                    if (statusMayHaveChanged) {
                        detailRefreshedAtSequence = newest?.sequence ?: detailRefreshedAtSequence
                        refreshDetailOnly(repo)
                    }
                    val approvalRelevant = snapshot.events.lastOrNull { it.type in APPROVAL_EVENTS }
                    if (approvalRelevant != null && approvalRelevant.sequence > approvalsLoadedAtSequence) {
                        approvalsLoadedAtSequence = approvalRelevant.sequence
                        loadApprovals()
                    }
                    delay(BATCH_MS)
                }
        }
    }

    /** Reads the current approvals; the server is the only source of what may be decided. */
    fun loadApprovals() {
        val repo = approvals ?: return
        viewModelScope.launch {
            when (val result = repo.list(taskId)) {
                is ApiResult.Success -> mutableState.update { it.copy(approvals = result.value) }
                is ApiResult.Failure -> Unit
            }
        }
    }

    /**
     * Decides exactly the action that was displayed: the digest of the displayed approval
     * is echoed, so the server refuses (Conflict) if the action changed or expired meanwhile.
     */
    fun decide(approval: Approval, approve: Boolean) {
        val repo = approvals ?: return
        if (mutableState.value.deciding) return
        mutableState.update { it.copy(deciding = true, decisionError = null) }
        viewModelScope.launch {
            when (val result = repo.decide(approval.id, approval.digest, approve)) {
                is ApiResult.Success -> mutableState.update { state ->
                    state.copy(
                        deciding = false,
                        approvals = state.approvals.map { if (it.id == result.value.id) result.value else it },
                    )
                }
                is ApiResult.Failure -> {
                    mutableState.update { it.copy(deciding = false, decisionError = result.error) }
                    loadApprovals() // show what the server now says about this action
                }
            }
        }
    }

    fun dismissDecisionError() {
        mutableState.update { it.copy(decisionError = null) }
    }

    fun stopStreaming() {
        syncJob?.cancel()
        syncJob = null
        mutableState.update { it.copy(stream = StreamState.Idle) }
        val store = lastSeen ?: return
        val sequence = timeline.lastSequence
        if (sequence > 0) viewModelScope.launch { store.put(taskId, sequence) }
    }

    private suspend fun refreshDetailOnly(repo: TaskRepository) {
        when (val result = repo.detail(taskId)) {
            is ApiResult.Success -> mutableState.update { it.copy(detail = result.value) }
            is ApiResult.Failure -> Unit // the timeline sync reports connectivity problems
        }
    }

    private suspend fun catchUpEvents(repo: TaskRepository): ApiError? {
        var pages = 0
        while (pages++ < MAX_PAGES) {
            when (val result = repo.events(taskId, timeline.lastSequence)) {
                is ApiResult.Failure -> return result.error
                is ApiResult.Success -> {
                    timeline.merge(result.value.items)
                    if (result.value.nextAfterSequence == null) return null
                }
            }
        }
        return null
    }

    class Factory(
        private val repository: TaskRepository?,
        private val stream: TaskEventStream?,
        private val lastSeen: LastSeenStore?,
        private val approvals: ApprovalRepository?,
        private val taskId: String,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(TaskDetailViewModel::class.java)) {
                "Unknown ViewModel class: ${modelClass.name}"
            }
            return TaskDetailViewModel(repository, stream, lastSeen, approvals, taskId) as T
        }
    }

    private companion object {
        const val MAX_PAGES = 50
        const val BATCH_MS = 150L
        val APPROVAL_EVENTS = setOf("APPROVAL_REQUESTED", "TASK_WAITING_APPROVAL", "TASK_APPROVAL_RESOLVED")
    }
}
