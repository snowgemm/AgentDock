package com.slg.agentdock.ui.tasks

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.net.ApiResult
import com.slg.agentdock.data.tasks.RemoteTask
import com.slg.agentdock.data.tasks.SubmissionTracker
import com.slg.agentdock.data.tasks.TaskRepository
import com.slg.agentdock.data.tasks.deriveTaskTitle
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class TaskListUiState(
    val items: List<RemoteTask> = emptyList(),
    val nextCursor: String? = null,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val loadedOnce: Boolean = false,
    val error: ApiError? = null,
)

data class SubmitUiState(
    val submitting: Boolean = false,
    val error: ApiError? = null,
)

sealed interface TasksEvent {
    /** The server accepted the draft; the caller may clear the local draft. */
    data class Submitted(val draftId: String, val taskId: String) : TasksEvent
}

/**
 * Server tasks for the signed-in user. Local drafts are not stored here: they remain
 * in the workspace tabs until the server has accepted them.
 */
class TasksViewModel(
    private val repository: TaskRepository?,
    signedIn: Flow<Boolean>,
    private val untitledFallback: String,
    private val tracker: SubmissionTracker = SubmissionTracker(),
) : ViewModel() {
    private val mutableList = MutableStateFlow(TaskListUiState())
    val list: StateFlow<TaskListUiState> = mutableList.asStateFlow()

    private val mutableSubmit = MutableStateFlow(SubmitUiState())
    val submit: StateFlow<SubmitUiState> = mutableSubmit.asStateFlow()

    private val mutableEvents = MutableSharedFlow<TasksEvent>(extraBufferCapacity = 1)
    val events: SharedFlow<TasksEvent> = mutableEvents.asSharedFlow()

    @Volatile
    private var isSignedIn = false

    init {
        viewModelScope.launch {
            signedIn.distinctUntilChanged().collect { value ->
                isSignedIn = value
                if (value) {
                    refresh()
                } else {
                    mutableList.value = TaskListUiState()
                    mutableSubmit.value = SubmitUiState()
                }
            }
        }
    }

    fun refresh() {
        val repo = repository ?: return
        if (!isSignedIn || mutableList.value.loading) return
        mutableList.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            when (val result = repo.list(cursor = null)) {
                is ApiResult.Success -> mutableList.value = TaskListUiState(
                    items = result.value.items,
                    nextCursor = result.value.nextCursor,
                    loadedOnce = true,
                )
                is ApiResult.Failure -> mutableList.update {
                    it.copy(loading = false, error = result.error)
                }
            }
        }
    }

    fun loadMore() {
        val repo = repository ?: return
        val state = mutableList.value
        val cursor = state.nextCursor ?: return
        if (!isSignedIn || state.loading || state.loadingMore) return
        mutableList.update { it.copy(loadingMore = true, error = null) }
        viewModelScope.launch {
            when (val result = repo.list(cursor)) {
                is ApiResult.Success -> mutableList.update { current ->
                    val known = current.items.mapTo(HashSet()) { it.id }
                    current.copy(
                        items = current.items + result.value.items.filter { it.id !in known },
                        nextCursor = result.value.nextCursor,
                        loadingMore = false,
                    )
                }
                is ApiResult.Failure -> mutableList.update {
                    it.copy(loadingMore = false, error = result.error)
                }
            }
        }
    }

    /** One call per user tap; a retry of unchanged content reuses its idempotency key. */
    fun submit(draftId: String, draft: String) {
        val repo = repository ?: return
        if (!isSignedIn || mutableSubmit.value.submitting || draft.isBlank()) return
        val title = deriveTaskTitle(draft, untitledFallback)
        val key = tracker.keyFor(draftId, title, draft)
        mutableSubmit.value = SubmitUiState(submitting = true)
        viewModelScope.launch {
            when (val result = repo.create(key, title, draft)) {
                is ApiResult.Success -> {
                    tracker.complete(draftId)
                    val created = result.value.task
                    mutableSubmit.value = SubmitUiState()
                    mutableList.update { current ->
                        current.copy(items = listOf(created) + current.items.filter { it.id != created.id })
                    }
                    mutableEvents.emit(TasksEvent.Submitted(draftId, created.id))
                }
                is ApiResult.Failure -> {
                    // Keep the key: the server may have accepted the request already.
                    mutableSubmit.value = SubmitUiState(error = result.error)
                }
            }
        }
    }

    fun dismissSubmitError() {
        mutableSubmit.update { it.copy(error = null) }
    }

    class Factory(
        private val repository: TaskRepository?,
        private val signedIn: Flow<Boolean>,
        private val untitledFallback: String,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(TasksViewModel::class.java)) {
                "Unknown ViewModel class: ${modelClass.name}"
            }
            return TasksViewModel(repository, signedIn, untitledFallback) as T
        }
    }
}
