/*
 * Namespace + capability primitives used to open a shell inside a
 * libvirt-LXC container. The composite entry point `enter_and_exec` performs
 * setns on the non-user namespaces first, then setns(CLONE_NEWUSER) (so
 * capability bounding-set drops and the explicit effective+permitted set
 * applied afterwards are not clobbered), then applies caps, then forks so
 * the exec'd shell lands in the container's PID namespace.
 *
 * Namespace fds are provided by the caller (typically via libvirt's
 * virDomainLxcOpenNamespace, exposed in Python as libvirt_lxc.lxcOpenNamespace)
 * rather than opened here from /proc/<pid>/ns/<kind>. The caller transfers
 * ownership of the fds to this function, which closes them after setns.
 *
 * Linked against -lc (setns, prctl, fork, execv, waitpid) and -lcap
 * (cap_from_name, cap_from_text, cap_set_proc, cap_free).
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <errno.h>
#include <grp.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/capability.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>


static PyObject *
py_setns(PyObject *self, PyObject *args)
{
    int fd, nstype;
    if (!PyArg_ParseTuple(args, "ii", &fd, &nstype))
        return NULL;
    if (setns(fd, nstype) != 0)
        return PyErr_SetFromErrno(PyExc_OSError);
    Py_RETURN_NONE;
}


static PyObject *
py_drop_bounding(PyObject *self, PyObject *args)
{
    int cap;
    if (!PyArg_ParseTuple(args, "i", &cap))
        return NULL;
    if (prctl(PR_CAPBSET_DROP, cap, 0, 0, 0) != 0)
        return PyErr_SetFromErrno(PyExc_OSError);
    Py_RETURN_NONE;
}


static PyObject *
py_cap_from_name(PyObject *self, PyObject *args)
{
    const char *name;
    cap_value_t cap;
    if (!PyArg_ParseTuple(args, "s", &name))
        return NULL;
    if (cap_from_name(name, &cap) != 0) {
        PyErr_Format(PyExc_ValueError, "unknown capability name: %s", name);
        return NULL;
    }
    return PyLong_FromLong((long)cap);
}


static PyObject *
py_cap_to_name(PyObject *self, PyObject *args)
{
    int cap;
    if (!PyArg_ParseTuple(args, "i", &cap))
        return NULL;
    char *name = cap_to_name((cap_value_t)cap);
    if (name == NULL)
        return PyErr_SetFromErrno(PyExc_OSError);
    PyObject *result = PyUnicode_FromString(name);
    cap_free(name);
    return result;
}


static PyObject *
py_cap_max_bits(PyObject *self, PyObject *args)
{
    if (!PyArg_ParseTuple(args, ""))
        return NULL;
    return PyLong_FromLong((long)cap_max_bits());
}


static PyObject *
py_cap_set_proc_from_text(PyObject *self, PyObject *args)
{
    const char *text;
    if (!PyArg_ParseTuple(args, "s", &text))
        return NULL;
    cap_t caps = cap_from_text(text);
    if (caps == NULL)
        return PyErr_SetFromErrno(PyExc_OSError);
    int rc = cap_set_proc(caps);
    int saved_errno = errno;
    cap_free(caps);
    if (rc != 0) {
        errno = saved_errno;
        return PyErr_SetFromErrno(PyExc_OSError);
    }
    Py_RETURN_NONE;
}


/*
 * enter_and_exec(user_fd, other_fds, drop_names, caps_text, argv) -> int
 *
 *   user_fd      (int):         fd for the container's user namespace, or
 *                               -1 to skip the user-ns switch
 *   other_fds    (list[int]):   fds for the non-user namespaces, applied
 *                               in order via setns(fd, 0) before the
 *                               user-ns switch. We pass nstype=0 (accept
 *                               any namespace type) so this code doesn't
 *                               need to know which fd is which kind.
 *   drop_names   (list[str]):   libcap names (e.g. "cap_lease") to drop
 *                               from CapBnd
 *   caps_text    (str):         libcap spec
 *                               (e.g. "cap_net_admin,cap_net_raw+ep"),
 *                               or empty string to skip
 *   argv         (list[str]):   command to exec inside the container
 *                               (argv[0] is the path to execv)
 *
 * Ownership: takes ownership of `user_fd` and every fd in `other_fds`;
 * they are closed by this function (either after successful setns or on
 * the error path).
 *
 * Returns the exit status of the exec'd process (parent side). Order of
 * operations is critical: setns(CLONE_NEWUSER) resets every capability set,
 * so drops + caps MUST be applied between the user-ns switch and the rest
 * of the setns calls.
 */
static PyObject *
py_enter_and_exec(PyObject *self, PyObject *args)
{
    int user_fd = -1;
    PyObject *other_fds_list, *drop_names_list, *argv_list;
    const char *caps_text;

    if (!PyArg_ParseTuple(args, "iO!O!sO!",
                          &user_fd,
                          &PyList_Type, &other_fds_list,
                          &PyList_Type, &drop_names_list,
                          &caps_text,
                          &PyList_Type, &argv_list))
        return NULL;

    Py_ssize_t n_other = PyList_GET_SIZE(other_fds_list);
    Py_ssize_t n_argv = PyList_GET_SIZE(argv_list);
    Py_ssize_t n_drops = PyList_GET_SIZE(drop_names_list);

    int *other_fd = NULL;
    int *drop_nums = NULL;
    char **argv = NULL;
    int had_user_fd = (user_fd >= 0);

    if (n_argv < 1) {
        PyErr_SetString(PyExc_ValueError, "argv must not be empty");
        goto err;
    }

    /* We take ownership of these fds from the caller — we must close
     * them all, even on the error path. */
    if (n_other > 0) {
        other_fd = PyMem_Malloc(n_other * sizeof(int));
        if (!other_fd) {
            PyErr_NoMemory();
            goto err;
        }
        for (Py_ssize_t i = 0; i < n_other; i++) {
            int fd = (int)PyLong_AsLong(PyList_GET_ITEM(other_fds_list, i));
            if (fd == -1 && PyErr_Occurred())
                goto err;
            other_fd[i] = fd;
        }
    }

    /* Resolve cap names to numbers before any setns — we still want Python
     * exceptions here to be reportable in the original environment. */
    if (n_drops > 0) {
        drop_nums = PyMem_Malloc(n_drops * sizeof(int));
        if (!drop_nums) {
            PyErr_NoMemory();
            goto err;
        }
        for (Py_ssize_t i = 0; i < n_drops; i++) {
            PyObject *item = PyList_GET_ITEM(drop_names_list, i);
            const char *name = PyUnicode_AsUTF8(item);
            if (!name)
                goto err;
            cap_value_t cap;
            if (cap_from_name(name, &cap) != 0) {
                PyErr_Format(PyExc_ValueError, "unknown capability name: %s", name);
                goto err;
            }
            drop_nums[i] = (int)cap;
        }
    }

    /* Build argv (borrowed pointers — valid until PyUnicode objects are
     * decref'd, which won't happen before execv). */
    argv = PyMem_Malloc((n_argv + 1) * sizeof(char *));
    if (!argv) {
        PyErr_NoMemory();
        goto err;
    }
    for (Py_ssize_t i = 0; i < n_argv; i++) {
        PyObject *item = PyList_GET_ITEM(argv_list, i);
        const char *s = PyUnicode_AsUTF8(item);
        if (!s)
            goto err;
        argv[i] = (char *)s;
    }
    argv[n_argv] = NULL;

    /* Ordering mirrors nsenter(1):
     *   parent: setns(all non-user) -> setns(user) -> cap adjustments -> fork
     *   child:  setgroups/setgid/setuid -> execve
     * User-ns switch happens AFTER the other namespaces (still in parent),
     * and the uid/gid change happens in the CHILD after fork. Doing setuid
     * in the parent doesn't propagate the expected in-namespace uid to the
     * child on execve (confirmed empirically against bare nsenter, which
     * only setuid's in the post-fork child). */
    for (Py_ssize_t i = 0; i < n_other; i++) {
        if (setns(other_fd[i], 0) != 0) {
            PyErr_SetFromErrno(PyExc_OSError);
            goto err;
        }
        close(other_fd[i]);
        other_fd[i] = -1;
    }
    if (user_fd >= 0) {
        if (setns(user_fd, 0) != 0) {
            PyErr_SetFromErrno(PyExc_OSError);
            goto err;
        }
        close(user_fd);
        user_fd = -1;
    }

    /* Apply bounding-set drops in the parent. Bounding-set drops survive
     * fork and execve; the child will inherit them. Must run after the
     * user-ns switch because setns(CLONE_NEWUSER) resets cap sets. */
    for (Py_ssize_t i = 0; i < n_drops; i++) {
        if (prctl(PR_CAPBSET_DROP, drop_nums[i], 0, 0, 0) != 0) {
            PyErr_SetFromErrno(PyExc_OSError);
            goto err;
        }
    }

    /* Apply effective+permitted set. Also inherited by the fork child. */
    if (caps_text[0] != '\0') {
        cap_t caps = cap_from_text(caps_text);
        if (caps == NULL) {
            PyErr_SetFromErrno(PyExc_OSError);
            goto err;
        }
        int rc = cap_set_proc(caps);
        int saved = errno;
        cap_free(caps);
        if (rc != 0) {
            errno = saved;
            PyErr_SetFromErrno(PyExc_OSError);
            goto err;
        }
    }

    /* setns(CLONE_NEWPID) only affects children — fork so the exec'd shell
     * lands in the container's PID namespace. The child also handles the
     * setuid/setgid dance that matches nsenter's --user default. */
    pid_t child = fork();
    if (child < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto err;
    }
    if (child == 0) {
        /* Mirror bare nsenter(1) behaviour for --user: drop supplementary
         * groups, then setgid(0) + setuid(0) so our kuid is re-anchored
         * through the container's user-namespace mapping. Doing this in the
         * child (not the parent) is what nsenter does; doing it in the
         * parent did not correctly propagate the in-namespace uid to the
         * exec'd shell. Only do this when the caller indicated a user-ns
         * entry — without one, we'd be running as host root and any such
         * call is redundant. */
        if (had_user_fd) {
            (void)setgroups(0, NULL);
            if (setgid(0) != 0) _exit(126);
            if (setuid(0) != 0) _exit(126);
        }
        execv(argv[0], argv);
        /* execv only returns on failure. */
        _exit(127);
    }

    PyMem_Free(argv);
    PyMem_Free(drop_nums);
    PyMem_Free(other_fd);

    int status;
    if (waitpid(child, &status, 0) < 0)
        return PyErr_SetFromErrno(PyExc_OSError);
    if (WIFEXITED(status))
        return PyLong_FromLong(WEXITSTATUS(status));
    if (WIFSIGNALED(status))
        return PyLong_FromLong(128 + WTERMSIG(status));
    return PyLong_FromLong(1);

err:
    if (user_fd >= 0) close(user_fd);
    if (other_fd) {
        for (Py_ssize_t i = 0; i < n_other; i++) {
            if (other_fd[i] >= 0) close(other_fd[i]);
        }
    }
    PyMem_Free(argv);
    PyMem_Free(drop_nums);
    PyMem_Free(other_fd);
    return NULL;
}


static PyMethodDef NsexecMethods[] = {
    {"setns",                   py_setns,                   METH_VARARGS,
     "setns(fd: int, nstype: int) -> None\n\n"
     "Thin wrapper over setns(2). `nstype` may be 0 to accept any namespace\n"
     "type, or one of CLONE_NEWUSER, CLONE_NEWNS, CLONE_NEWPID, etc."},
    {"drop_bounding",           py_drop_bounding,           METH_VARARGS,
     "drop_bounding(cap: int) -> None\n\n"
     "prctl(PR_CAPBSET_DROP, cap). Requires CAP_SETPCAP in the current\n"
     "user namespace. Drops survive execve(2) and non-user setns(2); they\n"
     "are reset by setns(CLONE_NEWUSER)."},
    {"cap_from_name",           py_cap_from_name,           METH_VARARGS,
     "cap_from_name(name: str) -> int\n\n"
     "Resolve a libcap text name (e.g. 'cap_lease') to its numeric value."},
    {"cap_to_name",             py_cap_to_name,             METH_VARARGS,
     "cap_to_name(cap: int) -> str\n\n"
     "Resolve a capability number to its libcap text name (e.g. 0 ->\n"
     "'cap_chown'). Unknown values come back as a bare decimal string."},
    {"cap_max_bits",            py_cap_max_bits,            METH_VARARGS,
     "cap_max_bits() -> int\n\n"
     "Return one past the highest capability number the running libcap /\n"
     "kernel recognises (reads /proc/sys/kernel/cap_last_cap)."},
    {"cap_set_proc_from_text",  py_cap_set_proc_from_text,  METH_VARARGS,
     "cap_set_proc_from_text(text: str) -> None\n\n"
     "Parse a libcap text spec (e.g. 'cap_net_admin,cap_net_raw+ep') and\n"
     "apply it as the calling thread's effective+permitted sets."},
    {"enter_and_exec",          py_enter_and_exec,          METH_VARARGS,
     "enter_and_exec(user_fd, other_fds, drop_names, caps_text, argv) -> int\n\n"
     "Enter the container's namespaces using caller-supplied fds (see\n"
     "libvirt_lxc.lxcOpenNamespace). other_fds is a list[int]; each fd is\n"
     "handed to setns(fd, 0) in list order, then user_fd (if >= 0) last.\n"
     "Cap drops and the explicit effective+permitted set are applied after\n"
     "the user-ns switch, then fork+exec. Takes ownership of all provided\n"
     "fds. Returns the exit status of the exec'd process."},
    {NULL, NULL, 0, NULL},
};


static struct PyModuleDef nsexec_module = {
    PyModuleDef_HEAD_INIT,
    "_native",
    "Namespace + capability primitives for container shell entry.",
    -1,
    NsexecMethods,
};


PyMODINIT_FUNC
PyInit__native(void)
{
    PyObject *m = PyModule_Create(&nsexec_module);
    if (m == NULL)
        return NULL;

    /* Expose the CLONE_NEW* flags from <linux/sched.h> (pulled in via
     * <sched.h>) as module attributes so callers can pass them to
     * enter_and_exec / setns without duplicating the values. */
    if (PyModule_AddIntConstant(m, "CLONE_NEWNS", CLONE_NEWNS) < 0 ||
        PyModule_AddIntConstant(m, "CLONE_NEWUTS", CLONE_NEWUTS) < 0 ||
        PyModule_AddIntConstant(m, "CLONE_NEWIPC", CLONE_NEWIPC) < 0 ||
        PyModule_AddIntConstant(m, "CLONE_NEWUSER", CLONE_NEWUSER) < 0 ||
        PyModule_AddIntConstant(m, "CLONE_NEWPID", CLONE_NEWPID) < 0 ||
        PyModule_AddIntConstant(m, "CLONE_NEWNET", CLONE_NEWNET) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
