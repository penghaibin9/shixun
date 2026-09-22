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
import LabsView from './views/LabsView.vue'
import LabTemplatesView from './views/LabTemplatesView.vue'
import LabKnowledgeView from './views/LabKnowledgeView.vue'
import LabBuilderView from './views/LabBuilderView.vue'
import RuntimeAdminView from './views/RuntimeAdminView.vue'
import LabLiveView from '../modules/lab-classroom/LabLiveView.vue'
import TeacherInstancesView from '../modules/lab-classroom/TeacherInstancesView.vue'
import TeacherLogsView from '../modules/lab-classroom/TeacherLogsView.vue'
import StudentLabView from '../modules/lab-classroom/StudentLabView.vue'
import StudentLogView from '../modules/lab-classroom/StudentLogView.vue'
import GradingView from './views/GradingView.vue'

export default createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/lifecycle' },
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
  { path: '/lab-live', component: LabLiveView },
  { path: '/teacher-instances', component: TeacherInstancesView },
  { path: '/teacher-logs', component: TeacherLogsView },
  { path: '/student-lab', component: StudentLabView },
  { path: '/student-log', component: StudentLogView },
  { path: '/teacher-grades', name: 'teacher-grades', component: GradingView, meta: { page: 'grades' } },
  { path: '/analytics', name: 'analytics', component: GradingView, meta: { page: 'analytics' } },
  { path: '/archive', name: 'archive', component: GradingView, meta: { page: 'archive' } },
  { path: '/student-score', name: 'student-score', component: GradingView, meta: { page: 'student' } },
  { path: '/admin-audit', name: 'admin-audit', component: GradingView, meta: { page: 'audit' } },
] })
