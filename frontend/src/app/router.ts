import { createRouter, createWebHistory } from 'vue-router'
import TeacherDashboard from './views/TeacherDashboard.vue'
import StudentHome from './views/StudentHome.vue'
import LifecycleView from './views/LifecycleView.vue'
import HandoffView from './views/HandoffView.vue'
import LabsView from './views/LabsView.vue'
import LabTemplatesView from './views/LabTemplatesView.vue'
import LabKnowledgeView from './views/LabKnowledgeView.vue'
import LabBuilderView from './views/LabBuilderView.vue'
import RuntimeAdminView from './views/RuntimeAdminView.vue'

export default createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/teacher-dashboard' },
  { path: '/teacher-dashboard', component: TeacherDashboard },
  { path: '/student-home', component: StudentHome },
  { path: '/lifecycle', component: LifecycleView },
  { path: '/handoff', component: HandoffView },
  { path: '/labs', component: LabsView },
  { path: '/lab-templates', component: LabTemplatesView },
  { path: '/course-knowledge', component: LabKnowledgeView },
  { path: '/lab-builder', component: LabBuilderView },
  { path: '/admin/overview', component: RuntimeAdminView },
  { path: '/admin/nodes', component: RuntimeAdminView },
  { path: '/admin/images', component: RuntimeAdminView },
  { path: '/admin/scheduler', component: RuntimeAdminView },
  { path: '/admin/network', component: RuntimeAdminView },
  { path: '/admin/instances', component: RuntimeAdminView },
  { path: '/admin/alerts', component: RuntimeAdminView },
  { path: '/admin/recovery', component: RuntimeAdminView },
] })
