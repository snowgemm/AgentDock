package com.slg.agentdock

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.ViewModelProvider
import com.slg.agentdock.ui.AgentDockApp
import com.slg.agentdock.ui.AgentDockViewModel
import com.slg.agentdock.ui.auth.AuthStatus
import com.slg.agentdock.ui.auth.AuthViewModel
import com.slg.agentdock.ui.tasks.TaskDetailViewModel
import com.slg.agentdock.ui.tasks.TasksViewModel
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        val app = application as AgentDockApplication
        val repository = app.workspaceRepository
        val auth = app.container.auth
        val viewModel = ViewModelProvider(
            this,
            AgentDockViewModel.Factory(repository),
        )[AgentDockViewModel::class.java]

        val authViewModel = ViewModelProvider(
            this,
            AuthViewModel.Factory(auth?.sessions, auth?.oidc),
        )[AuthViewModel::class.java]

        val signedIn = authViewModel.uiState
            .map { it.status == AuthStatus.SIGNED_IN }
            .distinctUntilChanged()
        val tasksViewModel = ViewModelProvider(
            this,
            TasksViewModel.Factory(auth?.tasks, signedIn, getString(R.string.new_task)),
        )[TasksViewModel::class.java]

        setContent {
            AgentDockApp(
                viewModel = viewModel,
                authViewModel = authViewModel,
                tasksViewModel = tasksViewModel,
                detailFactory = { taskId ->
                    TaskDetailViewModel.Factory(auth?.tasks, auth?.events, auth?.lastSeen, auth?.approvals, taskId)
                },
            )
        }
    }
}
