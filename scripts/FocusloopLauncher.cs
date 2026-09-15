using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace FocusloopLabsLauncher
{
    static class Program
    {
        [DllImport("shell32.dll", SetLastError = true)]
        static extern void SetCurrentProcessExplicitAppUserModelID([MarshalAs(UnmanagedType.LPWStr)] string AppID);

        [STAThread]
        static void Main(string[] args)
        {
            // Set AppUserModelID so Windows Taskbar groups under Focusloop Labs
            try
            {
                SetCurrentProcessExplicitAppUserModelID("focuslooplabs.studio.pro");
            }
            catch { }

            // Single-instance Mutex safeguard
            bool createdNew;
            using (Mutex mutex = new Mutex(true, "FocusloopLabs_SingleInstance_Mutex_9876", out createdNew))
            {
                if (!createdNew)
                {
                    MessageBox.Show("Focusloop Labs is already running.\nPlease check your taskbar or active windows.", "Focusloop Labs", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }

                string baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
                string mainPy = Path.Combine(baseDir, "main.py");

                if (!File.Exists(mainPy))
                {
                    MessageBox.Show("Could not find main.py in:\n" + baseDir, "Focusloop Labs Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                // Check Python installation candidates in priority order
                string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                string[] pythonCandidates = new string[]
                {
                    // 1. Bundled embedded or venv Python inside the application directory (Portable / Installed)
                    Path.Combine(baseDir, "python", "pythonw.exe"),
                    Path.Combine(baseDir, "python", "python.exe"),
                    Path.Combine(baseDir, "python", "Scripts", "pythonw.exe"),
                    Path.Combine(baseDir, "python", "Scripts", "python.exe"),
                    Path.Combine(baseDir, "venv", "Scripts", "pythonw.exe"),
                    Path.Combine(baseDir, "venv", "Scripts", "python.exe"),
                    // 3. User profile Python installations
                    Path.Combine(localAppData, "Programs", "Python", "Python311", "pythonw.exe"),
                    Path.Combine(localAppData, "Programs", "Python", "Python311", "python.exe"),
                    Path.Combine(localAppData, "Programs", "Python", "Python312", "pythonw.exe"),
                    Path.Combine(localAppData, "Programs", "Python", "Python312", "python.exe"),
                    // 4. System PATH candidates
                    "pythonw.exe",
                    "python.exe"
                };

                string pythonExe = null;
                foreach (string cand in pythonCandidates)
                {
                    if (Path.IsPathRooted(cand))
                    {
                        if (File.Exists(cand))
                        {
                            pythonExe = cand;
                            break;
                        }
                    }
                    else
                    {
                        string found = FindOnPath(cand);
                        if (!string.IsNullOrEmpty(found))
                        {
                            pythonExe = found;
                            break;
                        }
                    }
                }

                if (string.IsNullOrEmpty(pythonExe))
                {
                    MessageBox.Show(
                        "Python runtime was not found.\n\n" +
                        "For a portable installation, ensure the 'python' directory exists inside:\n" +
                        baseDir + "\n\n" +
                        "Alternatively, install Python 3.11 (64-bit) from https://www.python.org.",
                        "Focusloop Labs — Runtime Required",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                    return;
                }

                try
                {
                    ProcessStartInfo psi = new ProcessStartInfo();
                    psi.FileName = pythonExe;

                    string arguments = "\"" + mainPy + "\"";
                    if (args != null && args.Length > 0)
                    {
                        arguments += " " + string.Join(" ", args);
                    }
                    psi.Arguments = arguments;
                    psi.WorkingDirectory = baseDir;
                    psi.UseShellExecute = false;
                    psi.CreateNoWindow = true;
                    psi.WindowStyle = ProcessWindowStyle.Hidden;

                    using (Process proc = Process.Start(psi))
                    {
                        if (proc != null)
                        {
                            proc.WaitForExit();
                        }
                    }
                }
                catch (Exception ex)
                {
                    MessageBox.Show("Error launching Focusloop Labs:\n" + ex.Message, "Focusloop Labs Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
        }

        static string FindOnPath(string fileName)
        {
            string pathEnv = Environment.GetEnvironmentVariable("PATH");
            if (string.IsNullOrEmpty(pathEnv)) return null;

            string[] paths = pathEnv.Split(';');
            foreach (string p in paths)
            {
                try
                {
                    string trimmed = p.Trim();
                    if (!string.IsNullOrEmpty(trimmed))
                    {
                        string full = Path.Combine(trimmed, fileName);
                        if (File.Exists(full)) return full;
                    }
                }
                catch { }
            }
            return null;
        }
    }
}
