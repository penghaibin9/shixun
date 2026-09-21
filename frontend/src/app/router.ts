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
import CourseResourcesView from './views/CourseResourcesView.vue'

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
  { path: '/resources', name: 'resources', component: CourseResourcesView, meta: { page: 'overview' } },
  { path: '/course-blueprint', name: 'course-blueprint', component: CourseResourcesView, meta: { page: 'blueprint' } },
  { path: '/course-theory', name: 'course-theory', component: CourseResourcesView, meta: { page: 'theory' } },
  { path: '/course-lab-lessons', name: 'course-lab-lessons', component: CourseResourcesView, meta: { page: 'labs' } },
  { path: '/course-ppt', name: 'course-ppt', component: CourseResourcesView, meta: { page: 'ppt' } },
  { path: '/course-video', name: 'course-video', component: CourseResourcesView, meta: { page: 'video' } },
  { path: '/course-questions', name: 'course-questions', component: CourseResourcesView, meta: { page: 'questions' } },
  { path: '/course-procurement', name: 'course-procurement', component: CourseResourcesView, meta: { page: 'procurement' } },
  { path: '/course-resource-audit', name: 'course-resource-audit', component: CourseResourcesView, meta: { page: 'audit' } },
  { path: '/course-delivery', name: 'course-delivery', component: CourseResourcesView, meta: { page: 'delivery' } },
] })
