<!--
 |
 | XSLT REC Compliant Version of IE5 Default Stylesheet
 |
 | Original version by Jonathan Marsh (jmarsh@xxxxxxxxxxxxx)
 | http://msdn.microsoft.com/xml/samples/defaultss/defaultss.xsl
 |
 | Conversion to XSLT 1.0 REC Syntax by Steve Muench (smuench@xxxxxxxxxx)
 | Hyperlinking, misc mods by Anton Jouline (antonj@garagegames.com)
 |
 +-->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
   <xsl:output indent="no" method="html"/>

   <xsl:template match="/">
      <HTML>
         <HEAD>
            <STYLE>
              BODY  {font:0.96em 'Arial'; margin-right:1.5em}
                .b  {color:red; font-family:'Courier New'; font-weight:normal;
                     text-decoration:none}
                .e  {margin-left:1em; text-indent:-1em; margin-right:1em}
                .k  {margin-left:1em; text-indent:-1em; margin-right:1em}
                .t  {color:#848;font-weight:bold}
                .xt {color:#808;font-weight:bold}
                .ut {color:#484;font-weight:bold}
                .ta {color:#444;font-weight:bold}
                .xta{color:#808;font-weight:bold}
                .uta{color:#484;font-weight:bold}
                .av {color:#00c}
                .ns {color:red}
                .dt {color:green}
                .m  {color:black}
                .tx {font-weight:normal}
                .db {text-indent:0px; margin-left:1em; margin-top:0px;
                     margin-bottom:0px;padding-left:.3em;
                     border-left:1px solid #CCCCCC; font:small Courier}
                .di {font:small Courier}
                .d  {color:blue}
                .pi {color:blue}
                .cb {text-indent:0px; margin-left:1em; margin-top:0px;
                     margin-bottom:0px;padding-left:.3em; font:small Courier;
                     color:#888888}
                .ci {font:small Courier; color:#888888}
                a          {color:#080;text-decoration:none}
                a:hover    {background-color:#dfd;text-decoration:underline}
                PRE {margin:0px; display:inline}
           </STYLE>
         </HEAD>
         <BODY class="st">
            <xsl:apply-templates/>
         </BODY>
      </HTML>
   </xsl:template>

   <xsl:template match="@*">
      <SPAN>
         <xsl:attribute name="class">
            <xsl:choose>
                <xsl:when test="xsl:*/@*">
                  <xsl:text>x</xsl:text>
                </xsl:when>
                <xsl:when test="name(.)='URI'">
                  <xsl:text>u</xsl:text>
                </xsl:when>
            </xsl:choose>
            <xsl:text>ta</xsl:text>
         </xsl:attribute>
         <xsl:value-of select="name(.)"/>
      </SPAN>
      <SPAN class="m">="</SPAN>
      <xsl:choose>
        <xsl:when test="name(.)='URI'">
          <a href="{.}"><xsl:value-of select="."/></a>
        </xsl:when>
        <xsl:when test="name(.)='href'">
          <a href="{.}"><xsl:value-of select="."/></a>
        </xsl:when>
        <xsl:otherwise>
          <SPAN class="av"><xsl:value-of select="."/></SPAN>
        </xsl:otherwise>
      </xsl:choose>
      <SPAN class="m">" </SPAN>
   </xsl:template>

   <xsl:template match="text()">
      <DIV class="e">
         <SPAN class="b"> </SPAN>
         <SPAN class="tx">
            <xsl:value-of select="."/>
         </SPAN>
      </DIV>
   </xsl:template>

   <xsl:template match="comment()">
      <DIV class="k">
         <SPAN>
            <SPAN class="m">
               <xsl:text>&lt;!--</xsl:text>
            </SPAN>
         </SPAN>
         <SPAN class="ci" id="clean">
            <PRE>
               <xsl:value-of select="."/>
            </PRE>
         </SPAN>
         <SPAN class="m">
            <xsl:text>--&gt;</xsl:text>
         </SPAN>
         <SCRIPT>f(clean);</SCRIPT>
      </DIV>
   </xsl:template>

   <xsl:template match="*">
      <DIV class="e">
         <DIV STYLE="margin-left:1em;text-indent:-2em">
            <SPAN class="m">&lt;</SPAN>
            <SPAN>
               <xsl:attribute name="class">
                  <xsl:if test="xsl:*">
                     <xsl:text>x</xsl:text>
                  </xsl:if>
                  <xsl:text>t</xsl:text>
               </xsl:attribute>
               <xsl:value-of select="name(.)"/>
               <xsl:if test="@*">
                  <xsl:text> </xsl:text>
               </xsl:if>
            </SPAN>
            <xsl:apply-templates select="@*"/>
            <SPAN class="m">
               <xsl:text>/&gt;</xsl:text>
            </SPAN>
         </DIV>
      </DIV>
   </xsl:template>

   <xsl:template match="*[node()]">
      <DIV class="e">
         <DIV class="c">
            <SPAN class="m">&lt;</SPAN>
            <SPAN>
               <xsl:attribute name="class">
                  <xsl:if test="xsl:*">
                     <xsl:text>x</xsl:text>
                  </xsl:if>
                  <xsl:text>t</xsl:text>
               </xsl:attribute>
               <xsl:value-of select="name(.)"/>
               <xsl:if test="@*">
                  <xsl:text> </xsl:text>
               </xsl:if>
            </SPAN>
            <xsl:apply-templates select="@*"/>
            <SPAN class="m">
               <xsl:text>&gt;</xsl:text>
            </SPAN>
         </DIV>
         <DIV>
            <xsl:apply-templates/>
            <DIV>
               <SPAN class="m">
                  <xsl:text>&lt;/</xsl:text>
               </SPAN>
               <SPAN>
                  <xsl:attribute name="class">
                     <xsl:if test="xsl:*">
                        <xsl:text>x</xsl:text>
                     </xsl:if>
                     <xsl:text>t</xsl:text>
                  </xsl:attribute>
                  <xsl:value-of select="name(.)"/>
               </SPAN>
               <SPAN class="m">
                  <xsl:text>&gt;</xsl:text>
               </SPAN>
            </DIV>
         </DIV>
      </DIV>
   </xsl:template>

   <xsl:template match="*[text() and not (comment() or processing-instruction())]">
      <DIV class="e">
         <DIV STYLE="margin-left:1em;text-indent:-2em">
            <SPAN class="m">
               <xsl:text>&lt;</xsl:text>
            </SPAN>
            <SPAN>
               <xsl:attribute name="class">
                  <xsl:if test="xsl:*">
                     <xsl:text>x</xsl:text>
                  </xsl:if>
                  <xsl:text>t</xsl:text>
               </xsl:attribute>
               <xsl:value-of select="name(.)"/>
               <xsl:if test="@*">
                  <xsl:text> </xsl:text>
               </xsl:if>
            </SPAN>
            <xsl:apply-templates select="@*"/>
            <SPAN class="m">
               <xsl:text>&gt;</xsl:text>
            </SPAN>
            <PRE>
               <xsl:value-of select="."/>
            </PRE>
            <SPAN class="m">&lt;/</SPAN>
            <SPAN>
               <xsl:attribute name="class">
                  <xsl:if test="xsl:*">
                     <xsl:text>x</xsl:text>
                  </xsl:if>
                  <xsl:text>t</xsl:text>
               </xsl:attribute>
               <xsl:value-of select="name(.)"/>
            </SPAN>
            <SPAN class="m">
               <xsl:text>&gt;</xsl:text>
            </SPAN>
         </DIV>
      </DIV>
   </xsl:template>

   <xsl:template match="*[*]" priority="20">
      <DIV class="e">
         <DIV STYLE="margin-left:1em;text-indent:-2em" class="c">
            <SPAN class="m">&lt;</SPAN>
            <SPAN>
               <xsl:attribute name="class">
                  <xsl:if test="xsl:*">
                     <xsl:text>x</xsl:text>
                  </xsl:if>
                  <xsl:text>t</xsl:text>
               </xsl:attribute>
               <xsl:value-of select="name(.)"/>
               <xsl:if test="@*">
                  <xsl:text> </xsl:text>
               </xsl:if>
            </SPAN>
            <xsl:apply-templates select="@*"/>
            <SPAN class="m">
               <xsl:text>&gt;</xsl:text>
            </SPAN>
         </DIV>
         <DIV>
            <xsl:apply-templates/>
            <DIV>
               <SPAN class="m">
                  <xsl:text>&lt;/</xsl:text>
               </SPAN>
               <SPAN>
                  <xsl:attribute name="class">
                     <xsl:if test="xsl:*">
                        <xsl:text>x</xsl:text>
                     </xsl:if>
                     <xsl:text>t</xsl:text>
                  </xsl:attribute>
                  <xsl:value-of select="name(.)"/>
               </SPAN>
               <SPAN class="m">
                  <xsl:text>&gt;</xsl:text>
               </SPAN>
            </DIV>
         </DIV>
      </DIV>
   </xsl:template>

   <xsl:template match="URI" priority="1">
       <xsl:variable name="link" select="text()"/>
       <DIV class="e">
           <DIV STYLE="margin-left:1em;text-indent:-2em" class="c">
           <SPAN class="m">&lt;</SPAN>
           <SPAN class="ut">URI</SPAN>
           <SPAN class="m">&gt;</SPAN>
           <a href="{$link}"><xsl:value-of select="$link"/></a>
           <SPAN class="m">&lt;</SPAN>
           <SPAN class="ut">/URI</SPAN>
           <SPAN class="m">&gt;</SPAN>
           </DIV>
       </DIV>
   </xsl:template>

   <xsl:template name="entity-ref">
      <xsl:param name="name"/>
      <xsl:text disable-output-escaping="yes">&amp;</xsl:text>
      <xsl:value-of select="$name"/>
      <xsl:text>;</xsl:text>
   </xsl:template>

</xsl:stylesheet>