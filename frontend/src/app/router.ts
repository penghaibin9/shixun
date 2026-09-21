import { createRouter, createWebHistory } from 'vue-router'
import TeacherDashboard from './views/TeacherDashboard.vue'
import StudentHome from './views/StudentHome.vue'
import LifecycleView from './views/LifecycleView.vue'
import HandoffView from './views/HandoffView.vue'
import GradingView from './views/GradingView.vue'

export default createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/teacher-dashboard' },
  { path: '/teacher-dashboard', component: TeacherDashboard },
  { path: '/student-home', component: StudentHome },
  { path: '/lifecycle', component: LifecycleView },
  { path: '/handoff', component: HandoffView },
  { path: '/teacher-grades', name: 'teacher-grades', component: GradingView, meta: { page: 'grades' } },
  { path: '/analytics', name: 'analytics', component: GradingView, meta: { page: 'analytics' } },
  { path: '/archive', name: 'archive', component: GradingView, meta: { page: 'archive' } },
  { path: '/student-score', name: 'student-score', component: GradingView, meta: { page: 'student' } },
  { path: '/admin-audit', name: 'admin-audit', component: GradingView, meta: { page: 'audit' } },
] })
