import { createRouter, createWebHistory } from 'vue-router'
import TeacherDashboard from './views/TeacherDashboard.vue'
import StudentHome from './views/StudentHome.vue'
import LifecycleView from './views/LifecycleView.vue'
import HandoffView from './views/HandoffView.vue'
import LabLiveView from '../modules/lab-classroom/LabLiveView.vue'
import TeacherInstancesView from '../modules/lab-classroom/TeacherInstancesView.vue'
import TeacherLogsView from '../modules/lab-classroom/TeacherLogsView.vue'
import StudentLabView from '../modules/lab-classroom/StudentLabView.vue'
import StudentLogView from '../modules/lab-classroom/StudentLogView.vue'

export default createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/teacher-dashboard' },
  { path: '/teacher-dashboard', component: TeacherDashboard },
  { path: '/student-home', component: StudentHome },
  { path: '/lifecycle', component: LifecycleView },
  { path: '/handoff', component: HandoffView },
  { path: '/lab-live', component: LabLiveView },
  { path: '/teacher-instances', component: TeacherInstancesView },
  { path: '/teacher-logs', component: TeacherLogsView },
  { path: '/student-lab', component: StudentLabView },
  { path: '/student-log', component: StudentLogView },
] })
