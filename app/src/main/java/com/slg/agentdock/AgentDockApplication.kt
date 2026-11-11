package com.slg.agentdock

import android.app.Application
import com.slg.agentdock.data.repository.DefaultWorkspaceRepository
import com.slg.agentdock.data.repository.WorkspaceRepository

class AgentDockApplication : Application() {
    val workspaceRepository: WorkspaceRepository by lazy {
        DefaultWorkspaceRepository(this)
    }

    val container: AppContainer by lazy { AppContainer(this) }
}
