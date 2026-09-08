using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace SaveSpaceLauncher
{
    static class Program
    {
        [DllImport("shell32.dll", SetLastError = true)]
        static extern void SetCurrentProcessExplicitAppUserModelID([MarshalAs(UnmanagedType.LPWStr)] string AppID);

        [STAThread]
        static void Main(string[] args)
        {
            // Set AppUserModelID so Windows Taskbar groups under SaveSpace Pro
            try
            {
                SetCurrentProcessExplicitAppUserModelID("verycosmicstuff.savespace.pro");
            }
            catch { }

            // Single-instance Mutex safeguard
            bool createdNew;
            using (Mutex mutex = new Mutex(true, "SaveSpace_SingleInstance_Mutex_9876", out createdNew))
            {
                if (!createdNew)
                {
                    MessageBox.Show("SaveSpace is already running.\nPlease check your taskbar or active windows.", "SaveSpace Pro", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }

                string baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
                string mainPy = Path.Combine(baseDir, "main.py");

                if (!File.Exists(mainPy))
                {
                    MessageBox.Show("Could not find main.py in:\n" + baseDir, "SaveSpace Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                // Check Python 3.11 installation candidates
                string[] pythonCandidates = new string[]
                {
                    @"C:\Users\Sunny\AppData\Local\Programs\Python\Python311\pythonw.exe",
                    @"C:\Users\Sunny\AppData\Local\Programs\Python\Python311\python.exe",
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
                    MessageBox.Show("Python 3.11 was not found on your system.\nPlease ensure Python 3.11 is installed.", "SaveSpace Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
                    MessageBox.Show("Error launching SaveSpace:\n" + ex.Message, "SaveSpace Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
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
