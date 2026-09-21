import { createRouter, createWebHistory } from 'vue-router'
import TeacherDashboard from './views/TeacherDashboard.vue'
import StudentHome from './views/StudentHome.vue'
import LifecycleView from './views/LifecycleView.vue'
import HandoffView from './views/HandoffView.vue'

export default createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/teacher-dashboard' },
  { path: '/teacher-dashboard', component: TeacherDashboard },
  { path: '/student-home', component: StudentHome },
  { path: '/lifecycle', component: LifecycleView },
  { path: '/handoff', component: HandoffView },
] })
