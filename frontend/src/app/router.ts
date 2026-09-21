import { createRouter, createWebHistory } from 'vue-router'
import TeacherDashboard from './views/TeacherDashboard.vue'
import StudentHome from './views/StudentHome.vue'
import LifecycleView from './views/LifecycleView.vue'
import HandoffView from './views/HandoffView.vue'
import CoursesView from './views/CoursesView.vue'
import TeacherStudentsView from './views/TeacherStudentsView.vue'
import AttendanceManagementView from './views/AttendanceManagementView.vue'
import TeacherAssignmentsView from './views/TeacherAssignmentsView.vue'
import StudentCourseView from './views/StudentCourseView.vue'
import StudentAttendanceView from './views/StudentAttendanceView.vue'
import StudentQuizView from './views/StudentQuizView.vue'

export default createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/teacher-dashboard' },
  { path: '/teacher-dashboard', component: TeacherDashboard },
  { path: '/student-home', component: StudentHome },
  { path: '/lifecycle', component: LifecycleView },
  { path: '/handoff', component: HandoffView },
  { path: '/courses', component: CoursesView },
  { path: '/teacher-students', component: TeacherStudentsView },
  { path: '/attendance-management', component: AttendanceManagementView },
  { path: '/teacher-assignments', component: TeacherAssignmentsView },
  { path: '/student-course', component: StudentCourseView },
  { path: '/student-attendance', component: StudentAttendanceView },
  { path: '/student-attendance/:token', component: StudentAttendanceView },
  { path: '/student-quiz', component: StudentQuizView },
] })
