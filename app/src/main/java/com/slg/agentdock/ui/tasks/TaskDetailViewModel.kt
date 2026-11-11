package com.slg.agentdock.ui.tasks

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.net.ApiResult
import com.slg.agentdock.data.tasks.RemoteTaskDetail
import com.slg.agentdock.data.tasks.TaskEvent
import com.slg.agentdock.data.tasks.TaskRepository
import com.slg.agentdock.data.tasks.TimelineBuffer
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class TaskDetailUiState(
    val detail: RemoteTaskDetail? = null,
    val events: List<TaskEvent> = emptyList(),
    val loading: Boolean = false,
    val error: ApiError? = null,
)

class TaskDetailViewModel(
    private val repository: TaskRepository?,
    private val taskId: String,
) : ViewModel() {
    private val timeline = TimelineBuffer()
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
        private val taskId: String,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(TaskDetailViewModel::class.java)) {
                "Unknown ViewModel class: ${modelClass.name}"
            }
            return TaskDetailViewModel(repository, taskId) as T
        }
    }

    private companion object {
        const val MAX_PAGES = 50
    }
}
