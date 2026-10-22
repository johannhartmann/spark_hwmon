// Select a local, matching PDB before Ghidra's normal analysis.
//@category SPBM
import ghidra.app.script.GhidraScript;
import ghidra.app.plugin.core.analysis.PdbUniversalAnalyzer;
import java.io.File;

public class SetLocalPdb extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("Local PDB path required");
        File pdb = new File(args[0]);
        if (!pdb.isFile()) throw new IllegalArgumentException("PDB does not exist: " + pdb);
        PdbUniversalAnalyzer.setPdbFileOption(currentProgram, pdb);
    }
}
