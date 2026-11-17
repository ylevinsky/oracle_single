# Shared Windows Credential Manager helpers for Hermes pool scripts.
# Dot-source from set-hermes-openai-pool-credential.ps1 and add-hermes-openai-pool-key.ps1

if (-not ("HermesCred.Manager" -as [type])) {
    $source = @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace HermesCred {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public uint Flags;
        public uint Type;
        public string TargetName;
        public string Comment;
        public long LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    public static class Manager {
        private const uint CredTypeGeneric = 1;
        private const uint CredPersistLocalMachine = 2;

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CredRead(string target, uint type, uint reserved, out IntPtr credential);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern bool CredWrite(ref CREDENTIAL userCredential, uint flags);

        [DllImport("advapi32.dll")]
        private static extern void CredFree(IntPtr buffer);

        public static void Write(string target, string userName, string secret) {
            byte[] blob = Encoding.Unicode.GetBytes(secret);
            IntPtr blobPtr = Marshal.AllocHGlobal(blob.Length);
            try {
                Marshal.Copy(blob, 0, blobPtr, blob.Length);
                var cred = new CREDENTIAL {
                    Type = CredTypeGeneric,
                    TargetName = target,
                    UserName = userName,
                    CredentialBlobSize = (uint)blob.Length,
                    CredentialBlob = blobPtr,
                    Persist = CredPersistLocalMachine
                };
                if (!CredWrite(ref cred, 0)) {
                    throw new System.ComponentModel.Win32Exception();
                }
            } finally {
                Marshal.ZeroFreeGlobalAllocUnicode(blobPtr);
            }
        }

        public static (string UserName, string Secret) Read(string target) {
            IntPtr nCredPtr = IntPtr.Zero;
            if (!CredRead(target, CredTypeGeneric, 0, out nCredPtr)) {
                throw new System.ComponentModel.Win32Exception();
            }
            try {
                var cred = (CREDENTIAL)Marshal.PtrToStructure(nCredPtr, typeof(CREDENTIAL));
                if (cred.CredentialBlobSize == 0) {
                    return (cred.UserName, string.Empty);
                }
                byte[] blob = new byte[cred.CredentialBlobSize];
                Marshal.Copy(cred.CredentialBlob, blob, 0, (int)cred.CredentialBlobSize);
                string secret = Encoding.Unicode.GetString(blob).TrimEnd('\0');
                return (cred.UserName, secret);
            } finally {
                CredFree(nCredPtr);
            }
        }
    }
}
'@
    Add-Type -TypeDefinition $source -Language CSharp
}
