// Export decompiled functions and call edges locally; never execute the driver.
// Proprietary decompiler output belongs outside the repository.
//@category SPBM
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.*;
import java.util.*;
import com.google.gson.GsonBuilder;

public class ExportAnalysis extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("Output directory required");
        File directory = new File(args[0]);
        if (!directory.isDirectory() && !directory.mkdirs())
            throw new IOException("Cannot create output directory: " + directory);
        long base = currentProgram.getImageBase().getOffset();
        DecompInterface decompiler = new DecompInterface();
        if (!decompiler.openProgram(currentProgram)) throw new IOException(decompiler.getLastMessage());
        List<Map<String,Object>> functions = new ArrayList<>();
        try (PrintWriter code = new PrintWriter(new File(directory, "functions.c"))) {
            FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
            while (iterator.hasNext()) {
                monitor.checkCancelled();
                Function function = iterator.next();
                if (function.isExternal()) continue;
                Map<String,Object> entry = new LinkedHashMap<>();
                long rva = function.getEntryPoint().getOffset() - base;
                entry.put("rva", String.format("0x%x", rva));
                entry.put("name", function.getName());
                entry.put("bytes", function.getBody().getNumAddresses());
                List<String> calls = new ArrayList<>();
                for (Function callee: function.getCalledFunctions(monitor))
                    calls.add(callee.getName() + "@" + callee.getEntryPoint());
                Collections.sort(calls);
                entry.put("calls", calls);
                DecompileResults result = decompiler.decompileFunction(function, 20, monitor);
                entry.put("decompiled", result.decompileCompleted());
                entry.put("error", result.getErrorMessage());
                code.printf("\n/* RVA 0x%x: %s */\n", rva, function.getName());
                if (result.decompileCompleted()) code.println(result.getDecompiledFunction().getC());
                functions.add(entry);
            }
        } finally { decompiler.dispose(); }
        try (Writer out = new FileWriter(new File(directory, "functions.json"))) {
            new GsonBuilder().setPrettyPrinting().create().toJson(functions, out);
        }
        println("Exported " + functions.size() + " functions to " + directory);
    }
}
