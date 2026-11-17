<?xml version="1.0" encoding="UTF-8"?>
<SCL xmlns="http://www.iec.ch/61850/2003/SCL" version="2007" revision="B">
  <Header id="GOOSE_PUB_DEMO" version="1" revision="1" nameStructure="IEDName"/>
  
  <!-- ====================== IED / 逻辑模型 ====================== -->
  <IED name="IED_PUB">
    <AccessPoint name="AP1">
      <Server>
        <!-- --------- LDevice: demoLD --------- -->
        <LDevice inst="demoLD">
          <LN0 lnClass="LLN0" inst="">
            <!-- DataSet: ds1 （1个 BOOL） -->
            <DataSet name="ds1">
              <!-- BOOL: demoLD/GGIO1.Ind1.stVal (ST) -->
              <FCDA ldInst="demoLD" lnClass="GGIO" lnInst="1" doName="Ind1" daName="stVal" fc="ST"/>
            </DataSet>
            <!-- DataSet: ds2 （1个 BOOL） -->
            <DataSet name="ds2">
              <!-- BOOL: demoLD/GGIO1.Ind2.stVal (ST) -->
              <FCDA ldInst="demoLD" lnClass="GGIO" lnInst="1" doName="Ind2" daName="stVal" fc="ST"/>
            </DataSet>
            <!-- DataSet: ds3 （顺序必须与发布端一致：先 U16/整数，再 BOOL） -->
            <DataSet name="ds3">
              <!-- U16（以整数承载）：demoLD/GGIO1.AnIn1.mag.i (MX) -->
              <FCDA ldInst="demoLD" lnClass="GGIO" lnInst="1" doName="AnIn1" daName="mag.i" fc="MX"/>
              <!-- BOOL：demoLD/GGIO1.Ind3.stVal (ST) -->
              <FCDA ldInst="demoLD" lnClass="GGIO" lnInst="1" doName="Ind3" daName="stVal" fc="ST"/>
            </DataSet>

            <!-- GOOSE 控制块：gcb1 / gcb2 / gcb3 -->
            <GSEControl name="gcb1" datSet="ds1" appID="4096" confRev="1" type="GOOSE" fixedOff="false" goID="gcb1"/>
            <GSEControl name="gcb2" datSet="ds2" appID="4097" confRev="1" type="GOOSE" fixedOff="false" goID="gcb2"/>
            <GSEControl name="gcb3" datSet="ds3" appID="4096" confRev="1" type="GOOSE" fixedOff="false" goID="gcb3"/>
          </LN0>

          <!-- 供 DataSet 引用的通用 I/O LN（示意） -->
          <LN lnClass="GGIO" inst="1" lnType="TGGIO"/>
        </LDevice>

        <!-- --------- LDevice: Feeder1 --------- -->
        <LDevice inst="Feeder1">
          <LN0 lnClass="LLN0" inst="">
            <!-- DataSet: TripDs （1个 BOOL，示例用 PTRC1.Tr.stVal） -->
            <DataSet name="TripDs">
              <FCDA ldInst="Feeder1" lnClass="PTRC" lnInst="1" doName="Tr" daName="stVal" fc="ST"/>
            </DataSet>

            <!-- GOOSE 控制块：Trip -->
            <GSEControl name="Trip" datSet="TripDs" appID="4098" confRev="1" type="GOOSE" fixedOff="false" goID="Trip"/>
          </LN0>

          <!-- 供 Trip 数据集引用的 LN（示意） -->
          <LN lnClass="PTRC" inst="1" lnType="TPTRC"/>
        </LDevice>
      </Server>
    </AccessPoint>
  </IED>

  <!-- ====================== 通信 / GOOSE 地址 ====================== -->
  <Communication>
    <SubNetwork name="ProcessBus" type="8-1">
      <ConnectedAP iedName="IED_PUB" apName="AP1">
        <!-- gcb1: demoLD/LLN0$GO$gcb1 -->
        <GSE ldInst="demoLD" cbName="gcb1">
          <Address>
            <P type="MAC-Address">01-0C-CD-01-00-01</P>
            <P type="APPID">4096</P>              <!-- 0x1000 -->
            <P type="VLAN-PRIORITY">4</P>
            <P type="VLAN-ID">000</P>             <!-- 不打Tag -->
            <P type="MinTime">4</P>
            <P type="MaxTime">5000</P>
          </Address>
        </GSE>

        <!-- gcb2: demoLD/LLN0$GO$gcb2 -->
        <GSE ldInst="demoLD" cbName="gcb2">
          <Address>
            <P type="MAC-Address">01-0C-CD-01-00-01</P>
            <P type="APPID">4097</P>              <!-- 0x1001 -->
            <P type="VLAN-PRIORITY">4</P>
            <P type="VLAN-ID">000</P>
            <P type="MinTime">4</P>
            <P type="MaxTime">5000</P>
          </Address>
        </GSE>

        <!-- Trip: Feeder1/LLN0$GO$Trip -->
        <GSE ldInst="Feeder1" cbName="Trip">
          <Address>
            <P type="MAC-Address">01-0C-CD-01-00-01</P>
            <P type="APPID">4098</P>              <!-- 0x1002 -->
            <P type="VLAN-PRIORITY">4</P>
            <P type="VLAN-ID">000</P>
            <P type="MinTime">4</P>
            <P type="MaxTime">5000</P>
          </Address>
        </GSE>

        <!-- gcb3: demoLD/LLN0$GO$gcb3（与 gcb1 同 APPID=4096，按你的代码保持一致） -->
        <GSE ldInst="demoLD" cbName="gcb3">
          <Address>
            <P type="MAC-Address">01-0C-CD-01-00-01</P>
            <P type="APPID">4096</P>              <!-- 0x1000 -->
            <P type="VLAN-PRIORITY">4</P>
            <P type="VLAN-ID">000</P>
            <P type="MinTime">4</P>
            <P type="MaxTime">5000</P>
          </Address>
        </GSE>
      </ConnectedAP>
    </SubNetwork>
  </Communication>

  <!-- ====================== （可选）类型模板占位 ====================== -->
  <DataTypeTemplates>
    <!-- 许多订阅端不强制校验模板；若你的工具需要严格模板，我再补齐下列 lnType/doType/daType 定义：
         - lnType="TGGIO"（GGIO 的 IndX、AnInX）
         - lnType="TPTRC"（PTRC 的 Tr）
         - 以及对应 DOType/DAType（SPS/MV 等 CDC）
    -->
  </DataTypeTemplates>
</SCL>
