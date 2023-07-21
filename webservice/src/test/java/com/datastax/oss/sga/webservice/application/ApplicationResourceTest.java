package com.datastax.oss.sga.webservice.application;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import com.datastax.oss.sga.cli.commands.applications.DeployApplicationCmd;
import com.datastax.oss.sga.impl.k8s.tests.KubeK3sServer;
import com.datastax.oss.sga.impl.storage.LocalStore;
import com.datastax.oss.sga.webservice.WebAppTestConfig;
import com.datastax.oss.sga.webservice.config.StorageProperties;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

import lombok.SneakyThrows;
import lombok.extern.slf4j.Slf4j;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@Slf4j
@Import(WebAppTestConfig.class)
@DirtiesContext
class ApplicationResourceTest {

    @Autowired
    MockMvc mockMvc;

    @RegisterExtension
    static final KubeK3sServer k3s = new KubeK3sServer(true);

    protected Path tempDir;

    @BeforeEach
    public void beforeEach(@TempDir Path tempDir) throws Exception {
        this.tempDir = tempDir;
    }

    protected File createTempFile(String content) {
        try {
            Path tempFile = Files.createTempFile(tempDir, "sga-cli-test", ".yaml");
            Files.write(tempFile, content.getBytes(StandardCharsets.UTF_8));
            return tempFile.toFile();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }



    private MockMultipartFile getMultipartFile(String application, String instance, String secrets) throws Exception {

        final Path zip = DeployApplicationCmd.buildZip(createTempFile(application),
                createTempFile(instance),
                createTempFile(secrets), s -> log.info(s));
        MockMultipartFile firstFile = new MockMultipartFile(
                "file", "content.zip", MediaType.APPLICATION_OCTET_STREAM_VALUE,
                Files.newInputStream(zip));
        return firstFile;

    }


    @Test
    void testAppCrud() throws Exception {
        mockMvc.perform(put("/api/tenants/my-tenant"))
                        .andExpect(status().isOk());
        mockMvc
                .perform(
                        multipart(HttpMethod.PUT, "/api/applications/my-tenant/test")
                                .file(getMultipartFile("""
                                                id: app1
                                                name: test
                                                topics: []
                                                pipeline: []
                                                """,
                                        """
                                                        instance:
                                                          streamingCluster:
                                                            type: pulsar
                                                        """,
                                        "secrets: []"))
                )
                .andExpect(status().isOk());

        mockMvc
                .perform(
                        get("/api/applications/my-tenant/test")
                )
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.applicationId").value("test"));

        mockMvc
                .perform(
                        get("/api/applications/my-tenant")
                )
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.test.applicationId").value("test"));

        mockMvc
                .perform(
                        delete("/api/applications/my-tenant/test")
                )
                .andExpect(status().isOk());

        mockMvc
                .perform(
                        get("/api/applications/my-tenant/test")
                )
                .andExpect(status().isNotFound());
    }

}